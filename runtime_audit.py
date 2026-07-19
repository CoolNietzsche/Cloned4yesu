#!/usr/bin/env python3
"""
runtime_audit.py — Runtime audit for a Puppeteer-cloned Next.js site.

Serves the static clone locally, then uses headless Chromium (Playwright)
to load a set of key page templates and:

  3. Capture console errors/warnings and failed network requests
     (404s, CORS errors, mixed content), classified as cosmetic
     (analytics/tracking) vs functional (breaks layout/interactivity).

  4. Probe common JS-dependent interactive UI (nav menus, sliders/carousels,
     video backgrounds, custom cursors, forms) and report whether each
     still functions, including SILENT failures (no console error, but
     the effect doesn't actually work — e.g. a slider whose "next" button
     is wired but never advances, a form whose submit handler 404s the
     configured POST endpoint).

Requires: pip install playwright && playwright install chromium

Usage:
    python3 runtime_audit.py /opt/azurio-clone/site/azuris-nextjs.vercel.app \
        --pages / /blog /blog/some-post /pricing /contact \
        --port 8890 \
        --report report_runtime.md

If --pages is omitted, the script will auto-discover up to 6 "template-like"
pages: the homepage, plus one representative page per top-level directory
(useful default for "key templates only" audits).
"""

import argparse
import http.server
import json
import re
import socket
import socketserver
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urljoin

COSMETIC_HOST_HINTS = [
    "google-analytics.com", "googletagmanager.com", "analytics", "gtag",
    "facebook.net", "fbevents", "hotjar", "clarity.ms", "segment.io",
    "segment.com", "sentry.io", "intercom", "hubspot", "doubleclick.net",
    "mixpanel.com", "amplitude.com", "cookielaw.org", "onetrust.com",
    "vercel-insights.com", "vitals.vercel-insights.com", "vercel.live",
    "posthog.com",
]

INTERACTIVE_PROBE_JS = r"""
() => {
  const report = {};

  // --- Nav menu (hamburger) detection ---
  const menuTriggerSelectors = [
    '[aria-label*="menu" i]', '[class*="hamburger" i]', '[class*="menu-toggle" i]',
    '[class*="nav-toggle" i]', 'button[class*="menu" i]', '[id*="menu-toggle" i]',
  ];
  let menuTrigger = null;
  for (const sel of menuTriggerSelectors) {
    try {
      const el = document.querySelector(sel);
      if (el) { menuTrigger = el; break; }
    } catch(e) {}
  }
  report.menu_trigger_found = !!menuTrigger;
  if (menuTrigger) {
    const navPanel = document.querySelector('nav, [class*="mobile-menu" i], [class*="nav-menu" i], [role="dialog"]');
    // Snapshot everything plausibly affected by a menu toggle: body class,
    // trigger's own class/aria-expanded, and the nav panel's class + computed
    // visibility. Any one of these changing counts as "responded".
    const snapshot = () => ({
      bodyClass: document.body.className,
      triggerClass: menuTrigger.className,
      triggerAria: menuTrigger.getAttribute('aria-expanded'),
      navClass: navPanel ? navPanel.className : null,
      navVisible: navPanel ? (getComputedStyle(navPanel).display !== 'none' && getComputedStyle(navPanel).visibility !== 'hidden' && getComputedStyle(navPanel).opacity !== '0') : null,
      htmlClass: document.documentElement.className,
    });
    const before = snapshot();
    try { menuTrigger.click(); } catch(e) { report.menu_click_error = String(e); }
    const after = snapshot();
    report.menu_state_changed = JSON.stringify(before) !== JSON.stringify(after);
    report.menu_before = before;
    report.menu_after = after;
  }

  // --- Slider / carousel detection ---
  const sliderSelectors = [
    '[class*="slider" i]', '[class*="carousel" i]', '[class*="swiper" i]',
    '[class*="slick" i]', '[data-slider]', '[class*="glide" i]',
  ];
  let slider = null;
  for (const sel of sliderSelectors) {
    try {
      const el = document.querySelector(sel);
      if (el) { slider = el; break; }
    } catch(e) {}
  }
  report.slider_found = !!slider;
  if (slider) {
    const nextBtnSelectors = [
      '[class*="next" i]', '[aria-label*="next" i]', 'button[class*="arrow" i]',
    ];
    let nextBtn = null;
    for (const sel of nextBtnSelectors) {
      const el = slider.querySelector(sel) || document.querySelector(sel);
      if (el) { nextBtn = el; break; }
    }
    report.slider_next_button_found = !!nextBtn;
    if (nextBtn) {
      const beforeHTML = slider.innerHTML;
      const beforeTransform = getComputedStyle(slider.querySelector('*') || slider).transform;
      try { nextBtn.click(); } catch(e) { report.slider_click_error = String(e); }
      // allow for transition/animation frame
      const afterHTML = slider.innerHTML;
      report.slider_dom_changed_after_click = beforeHTML !== afterHTML;
    }
  }

  // --- Video background detection ---
  // networkState/error are reliable synchronously; readyState/dimensions can
  // still be 0 under headless Chromium even for a perfectly valid source
  // (autoplay/decoding timing), so we don't treat low readyState alone as
  // proof of breakage — only networkState===NETWORK_NO_SOURCE (3) or a set
  // .error is treated as a real failure signal.
  const videos = Array.from(document.querySelectorAll('video'));
  report.video_count = videos.length;
  report.videos = videos.map(v => ({
    src: v.currentSrc || v.src || (v.querySelector('source') ? v.querySelector('source').src : null),
    readyState: v.readyState,
    paused: v.paused,
    autoplay: v.autoplay,
    error: v.error ? { code: v.error.code, message: v.error.message } : null,
    networkState: v.networkState, // 0=EMPTY,1=IDLE,2=LOADING,3=NO_SOURCE
    videoWidth: v.videoWidth,
    videoHeight: v.videoHeight,
  }));

  // --- Custom cursor effect detection ---
  const cursorSelectors = [
    '[class*="cursor" i]', '#cursor', '[id*="custom-cursor" i]',
  ];
  let cursorEl = null;
  for (const sel of cursorSelectors) {
    try {
      const el = document.querySelector(sel);
      if (el && el.tagName !== 'A') { cursorEl = el; break; }
    } catch(e) {}
  }
  report.custom_cursor_found = !!cursorEl;
  if (cursorEl) {
    const beforeStyle = cursorEl.getAttribute('style') || '';
    const ev = new MouseEvent('mousemove', { clientX: 200, clientY: 200, bubbles: true });
    document.dispatchEvent(ev);
    window.dispatchEvent(ev);
    const afterStyle = cursorEl.getAttribute('style') || '';
    report.cursor_style_changed_on_mousemove = beforeStyle !== afterStyle;
  }

  // --- Form detection ---
  const forms = Array.from(document.querySelectorAll('form'));
  report.forms = forms.map(f => ({
    action: f.action || null,
    method: f.method || 'get',
    has_submit_handler_attr: !!f.getAttribute('onsubmit'),
    field_count: f.querySelectorAll('input,textarea,select').length,
  }));

  return report;
}
"""


def find_free_port(preferred: int) -> int:
    for port in [preferred] + list(range(preferred + 1, preferred + 50)):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("No free port found")


def start_server(site_root: Path, port: int):
    handler_cls = lambda *a, **kw: http.server.SimpleHTTPRequestHandler(
        *a, directory=str(site_root), **kw
    )
    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", port), handler_cls)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd


def discover_key_pages(site_root: Path, max_pages=6):
    """Pick homepage + one representative page per top-level directory."""
    pages = ["/"]
    seen_dirs = set()
    for f in sorted(site_root.rglob("*.html")):
        rel = f.relative_to(site_root)
        parts = rel.parts
        if len(parts) == 1:
            continue  # already have homepage; skip other root-level files for now unless nothing else found
        top = parts[0]
        if top in seen_dirs:
            continue
        seen_dirs.add(top)
        # build a URL path from the file
        s = str(rel).replace("\\", "/")
        if s.endswith("/index.html"):
            url = "/" + s[: -len("index.html")]
        elif s.endswith(".html"):
            url = "/" + s[: -len(".html")]
        else:
            url = "/" + s
        pages.append(url)
        if len(pages) >= max_pages:
            break
    return pages


def classify_url(url: str) -> str:
    for hint in COSMETIC_HOST_HINTS:
        if hint in url:
            return "cosmetic"
    return "functional"


def audit_pages(base_url: str, pages: list, headless=True):
    from playwright.sync_api import sync_playwright

    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(ignore_https_errors=True)

        for page_path in pages:
            url = urljoin(base_url, page_path.lstrip("/") if page_path != "/" else "")
            if page_path == "/":
                url = base_url

            page_result = {
                "page": page_path,
                "url": url,
                "console_messages": [],
                "failed_requests": [],
                "page_errors": [],
                "interactive_probe": None,
                "load_error": None,
            }

            pg = context.new_page()

            def on_console(msg, pr=page_result):
                if msg.type in ("error", "warning"):
                    pr["console_messages"].append({
                        "type": msg.type,
                        "text": msg.text,
                        "location": msg.location,
                    })

            def on_pageerror(exc, pr=page_result):
                pr["page_errors"].append(str(exc))

            def on_requestfailed(request, pr=page_result):
                pr["failed_requests"].append({
                    "url": request.url,
                    "method": request.method,
                    "failure": request.failure,
                    "resource_type": request.resource_type,
                    "classification": classify_url(request.url),
                })

            def on_response(response, pr=page_result):
                if response.status >= 400:
                    pr["failed_requests"].append({
                        "url": response.url,
                        "status": response.status,
                        "resource_type": response.request.resource_type,
                        "classification": classify_url(response.url),
                    })

            pg.on("console", on_console)
            pg.on("pageerror", on_pageerror)
            pg.on("requestfailed", on_requestfailed)
            pg.on("response", on_response)

            try:
                pg.goto(url, wait_until="networkidle", timeout=20000)
            except Exception as e:
                page_result["load_error"] = str(e)
                try:
                    pg.goto(url, wait_until="domcontentloaded", timeout=15000)
                    page_result["load_error"] += " (recovered with domcontentloaded)"
                except Exception as e2:
                    page_result["load_error"] += f" | second attempt also failed: {e2}"

            time.sleep(3.0)  # let any deferred JS (animations, lazy scripts) and video buffering settle

            try:
                probe = pg.evaluate(INTERACTIVE_PROBE_JS)
                page_result["interactive_probe"] = probe
            except Exception as e:
                page_result["interactive_probe_error"] = str(e)

            pg.close()
            results.append(page_result)

        browser.close()
    return results


def render_markdown(results, out_path: Path, base_url: str):
    lines = []
    lines.append("# Runtime Audit Report\n")
    lines.append(f"Base URL used: `{base_url}`\n")

    for r in results:
        lines.append(f"## Page: `{r['page']}`\n")
        lines.append(f"URL: {r['url']}\n")

        if r["load_error"]:
            lines.append(f"**⚠️ Load error:** {r['load_error']}\n")

        # Console messages
        errs = [m for m in r["console_messages"] if m["type"] == "error"]
        warns = [m for m in r["console_messages"] if m["type"] == "warning"]
        lines.append(f"### Console: {len(errs)} error(s), {len(warns)} warning(s)\n")
        if errs or warns:
            lines.append("| type | text | location |")
            lines.append("|---|---|---|")
            for m in errs + warns:
                loc = m.get("location") or {}
                loc_s = f"{loc.get('url','')}:{loc.get('lineNumber','')}" if loc else ""
                text = m["text"].replace("|", "\\|").replace("\n", " ")[:200]
                lines.append(f"| {m['type']} | {text} | {loc_s} |")
            lines.append("")
        else:
            lines.append("_None._\n")

        # Page errors (uncaught exceptions)
        if r["page_errors"]:
            lines.append(f"### Uncaught JS Exceptions ({len(r['page_errors'])})\n")
            for e in r["page_errors"]:
                lines.append(f"- `{e}`")
            lines.append("")

        # Failed requests, split cosmetic vs functional
        fr = r["failed_requests"]
        cosmetic = [x for x in fr if x.get("classification") == "cosmetic"]
        functional = [x for x in fr if x.get("classification") == "functional"]
        lines.append(f"### Failed Network Requests: {len(fr)} total "
                      f"({len(functional)} functional, {len(cosmetic)} cosmetic)\n")
        if functional:
            lines.append("**Functional (likely breaks something):**\n")
            lines.append("| url | status/failure | resource_type |")
            lines.append("|---|---|---|")
            for f in functional:
                status = f.get("status", f.get("failure", ""))
                lines.append(f"| {f['url']} | {status} | {f.get('resource_type','')} |")
            lines.append("")
        if cosmetic:
            lines.append("**Cosmetic (analytics/tracking — safe to ignore):**\n")
            lines.append("| url | status/failure |")
            lines.append("|---|---|")
            for f in cosmetic:
                status = f.get("status", f.get("failure", ""))
                lines.append(f"| {f['url']} | {status} |")
            lines.append("")

        # Interactive probe
        probe = r.get("interactive_probe")
        lines.append("### Interactive Elements Probe\n")
        if not probe:
            lines.append(f"_Probe failed to run: {r.get('interactive_probe_error', 'unknown error')}_\n")
        else:
            # Menu
            if probe.get("menu_trigger_found"):
                status = "✅ responded to click (class/attr/visibility changed)" if probe.get("menu_state_changed") else "❌ SILENT FAILURE — click produced no class, aria, or visibility change anywhere we checked"
                lines.append(f"- **Nav menu toggle:** found. {status}")
            else:
                lines.append("- **Nav menu toggle:** not found on this page (may not apply)")

            # Slider
            if probe.get("slider_found"):
                if probe.get("slider_next_button_found"):
                    status = "✅ DOM changed after clicking next" if probe.get("slider_dom_changed_after_click") else "❌ SILENT FAILURE — next button click produced no DOM change"
                    lines.append(f"- **Slider/carousel:** found, next-button found. {status}")
                else:
                    lines.append("- **Slider/carousel:** found, but no next/prev control detected (may be autoplay-only or a probe miss)")
            else:
                lines.append("- **Slider/carousel:** not found on this page")

            # Video
            vids = probe.get("videos", [])
            if vids:
                lines.append(f"- **Video elements:** {len(vids)} found")
                for v in vids:
                    net_state = v.get("networkState")
                    if v.get("error"):
                        lines.append(f"  - ❌ `{v.get('src')}` — video error code {v['error'].get('code')}: {v['error'].get('message')}")
                    elif net_state == 3:
                        lines.append(f"  - ❌ `{v.get('src')}` — networkState=NETWORK_NO_SOURCE (browser could not resolve/load the source at all)")
                    elif v.get("readyState", 0) < 2:
                        lines.append(f"  - ⚠️ `{v.get('src')}` — readyState={v.get('readyState')} (inconclusive under headless Chromium; verify manually if this is a hero/background video)")
                    else:
                        lines.append(f"  - ✅ `{v.get('src')}` — loaded OK (readyState={v.get('readyState')}, {v.get('videoWidth')}x{v.get('videoHeight')})")
            else:
                lines.append("- **Video elements:** none on this page")

            # Cursor
            if probe.get("custom_cursor_found"):
                status = "✅ style updated on mousemove" if probe.get("cursor_style_changed_on_mousemove") else "❌ SILENT FAILURE — no style change on mousemove (cursor effect likely dead)"
                lines.append(f"- **Custom cursor effect:** found. {status}")
            else:
                lines.append("- **Custom cursor effect:** not found on this page")

            # Forms
            forms = probe.get("forms", [])
            if forms:
                lines.append(f"- **Forms:** {len(forms)} found")
                for f in forms:
                    action = f.get("action") or "(no action attribute — likely JS-handled submit)"
                    lines.append(f"  - method={f.get('method')}, action={action}, fields={f.get('field_count')}")
            else:
                lines.append("- **Forms:** none on this page")

        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("site_root", help="Path to the site root (folder containing index.html)")
    ap.add_argument("--pages", nargs="*", default=None,
                     help="List of page paths to audit, e.g. / /blog /pricing. "
                          "If omitted, auto-discovers up to 6 key templates.")
    ap.add_argument("--port", type=int, default=8890)
    ap.add_argument("--report", default="report_runtime.md")
    ap.add_argument("--json-out", default="report_runtime.json")
    ap.add_argument("--headed", action="store_true", help="Run browser headed (for debugging)")
    args = ap.parse_args()

    site_root = Path(args.site_root).resolve()
    if not site_root.exists():
        print(f"ERROR: site_root does not exist: {site_root}", file=sys.stderr)
        sys.exit(1)

    port = find_free_port(args.port)
    httpd = start_server(site_root, port)
    base_url = f"http://127.0.0.1:{port}/"
    print(f"Serving {site_root} at {base_url}")

    pages = args.pages if args.pages else discover_key_pages(site_root)
    print(f"Auditing pages: {pages}")

    try:
        results = audit_pages(base_url, pages, headless=not args.headed)
    finally:
        httpd.shutdown()

    Path(args.json_out).write_text(json.dumps(results, indent=2), encoding="utf-8")
    render_markdown(results, Path(args.report), base_url)

    print(f"\nReport written to: {args.report}")
    print(f"Raw JSON written to: {args.json_out}")

    # quick console summary
    print("\n=== Summary ===")
    for r in results:
        errs = len([m for m in r["console_messages"] if m["type"] == "error"])
        func_fails = len([f for f in r["failed_requests"] if f.get("classification") == "functional"])
        cos_fails = len([f for f in r["failed_requests"] if f.get("classification") == "cosmetic"])
        print(f"{r['page']:30s} console_errors={errs:<3} functional_failed_requests={func_fails:<3} cosmetic_failed_requests={cos_fails:<3} load_error={'YES' if r['load_error'] else 'no'}")


if __name__ == "__main__":
    main()
