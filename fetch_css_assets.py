#!/usr/bin/env python3
"""
fetch_css_assets.py

Fetches the assets referenced by CSS url() rules that static_audit.py flags
under "1d. CSS url(...) Issues". These live under /_next/static/media/ and
fall into three groups, all missing because the crawler never triggered a
network request for them (dark-mode CSS variants are never active during a
light-mode headless crawl; icon fonts are only requested if the page
actually renders a glyph from that font).

Groups:
  1. dark_demo_image - 10 dark-mode (--dark) variants of the "demo screen"
     background images used in .mxd-demo-grid__screen. The light-mode
     versions already exist on disk; these are the prefers-color-scheme:
     dark counterparts, referenced by CSS custom properties like
     --bg-demo-screen-01--dark. Two of the ten (02, 03, 06, 07, 09, 10 have
     the largest hash deltas) are confirmed genuinely different image
     bytes from their light counterparts, not just renamed duplicates.
  2. icon_font - the Phosphor icon font family (Bold/Duotone/Fill/Light/
     Thin/base, woff2/woff/ttf/svg) referenced from
     _next/static/chunks/0b3~ey51ozhxi.css. A same-named font exists on
     disk under a different hash - that's a different build; do not
     substitute it silently.
  3. body_font - the site's main text webfont (woff2), referenced from
     _next/static/chunks/0_6n635zsw8mc.css. Same situation: different
     hash exists locally, do not substitute.

This script does NOT guess at live-domain paths from filenames the way
fetch_remaining_assets.py did (those were app-manifest paths with fixed
names). Font/media hashes are content-addressed and specific to a build,
so instead this fetches each asset directly using the exact relative path
the CSS already references (the live domain will resolve them if that
build is still deployed).

Usage:
    pip install requests --break-system-packages
    python3 fetch_css_assets.py \
        --site-root /opt/azurio-clone/site/azuris-nextjs.vercel.app \
        --live-domain https://azuris-nextjs.vercel.app \
        --report fetch_css_assets_report.md \
        [--dry-run]
"""

import argparse
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: requests not installed. Run: pip install requests --break-system-packages", file=sys.stderr)
    sys.exit(1)

# All paths are relative to site root, matching the ../media/ resolution
# from _next/static/chunks/*.css -> _next/static/media/*

DARK_DEMO_IMAGES = [
    ("dark_demo_image", f"_next/static/media/{name}")
    for name in [
        "01-d.0~l45pyj1mx.e.webp",
        "02-d.0awe7rgex535w.webp",
        "03-d.09ore-w.y0jqt.webp",
        "04-d.0yfjk174~r9-p.webp",
        "05-d.08k847ck8wcli.webp",
        "06-d.060-zg1-byczy.webp",
        "07-d.0ixqq_b9ie_4..webp",
        "08-d.0.vdix4-27g1g.webp",
        "09-d.037lkqi7bfek2.webp",
        "10-d.0moy.5-9eng14.webp",
    ]
]

ICON_FONT = [
    ("icon_font", f"_next/static/media/{name}")
    for name in [
        "Phosphor-Bold.10~yyx1gycsl7.woff2",
        "Phosphor-Bold.08h-42032d85e.woff",
        "Phosphor-Bold.0~7w89f0d72t..ttf",
        "Phosphor-Bold.0nd3v-wz7lz3w.svg",
        "Phosphor-Duotone.0op6kpwxpjslq.woff2",
        "Phosphor-Duotone.0npiibimqhs1t.woff",
        "Phosphor-Duotone.0jgro-sl42oax.ttf",
        "Phosphor-Duotone.019smehihlzt-.svg",
        "Phosphor-Fill.0n-7d0vime5s0.woff2",
        "Phosphor-Fill.15gtd1~v3t66y.woff",
        "Phosphor-Fill.0oys~f4q.djtj.ttf",
        "Phosphor-Fill.0u96a4efsh5sx.svg",
        "Phosphor-Light.0q~b0vzzlywdc.woff2",
        "Phosphor-Light.0gs5cs32p6ht4.woff",
        "Phosphor-Light.0m_a49-ogc~b5.ttf",
        "Phosphor-Light.038ew-dfs2vmy.svg",
        "Phosphor.11wgiv9nqiit7.woff",
        "Phosphor.05iea4td0f2gq.ttf",
        "Phosphor.04kgtzk3bvjz2.svg",
        "Phosphor-Thin.0mupilx_je8d1.woff",
        "Phosphor-Thin.0~munq793kt8w.ttf",
        "Phosphor-Thin.0~54o~eo-eg8..svg",
    ]
]

BODY_FONT = [
    ("body_font", f"_next/static/media/{name}")
    for name in [
        "a342834df7752944-s.10ev4cu2inrn-.woff2",
        "d3fe2f289711ac3f-s.0i6ci0u~g4zml.woff2",
        "58c4895d0a0ef7cc-s.0x1a9yg0jkq20.woff2",
        "bfc7db5c00d21bc5-s.0dyk20wuvya7a.woff2",
        "6ab0db14f70d8ed6-s.0ctuso5mgh_i..woff2",
        "13bf9871fe164e7f-s.0s19wthhh_6~m.woff2",
        "cc545e633e20c56d-s.0dza.stei.9v7.woff2",
        "71b036adf157cdcf-s.03nf~dfjdkf~..woff2",
        "89b21bb081cb7469-s.0gfhww.tctz1o.woff2",
        "3fe682a82f50d426-s.09q3q1i5159bl.woff2",
    ]
]

ALL_ASSETS = DARK_DEMO_IMAGES + ICON_FONT + BODY_FONT


def sniff_ok(category: str, content: bytes, content_type: str) -> tuple[bool, str]:
    if len(content) < 16:
        return False, "response too short to be a real asset"

    head = content[:16]
    ctype = (content_type or "").lower()
    lowered_start = content[:500].lower()
    if b"<!doctype html" in lowered_start or b"<html" in lowered_start:
        return False, "looks like an HTML page (soft-404), not the real asset"

    if category == "dark_demo_image":
        if b"RIFF" in head[:4] or b"WEBP" in content[:16]:
            return True, "ok (webp)"
        return False, f"doesn't look like WEBP (content-type: {ctype})"

    if category in ("icon_font", "body_font"):
        # woff/woff2 magic: wOFF / wOF2 ; ttf: 00 01 00 00 or 'true'/'OTTO'; svg: text
        if head[:4] in (b"wOFF", b"wOF2") or head[:4] == b"\x00\x01\x00\x00" or head[:4] in (b"true", b"OTTO"):
            return True, "ok (font binary)"
        if b"<svg" in lowered_start or b"<?xml" in lowered_start:
            return True, "ok (svg font)"
        return False, f"doesn't look like a font file (content-type: {ctype})"

    return False, "unknown category"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--site-root", required=True)
    ap.add_argument("--live-domain", required=True)
    ap.add_argument("--report", default="fetch_css_assets_report.md")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--delay", type=float, default=0.3)
    args = ap.parse_args()

    site_root = Path(args.site_root).resolve()
    if not site_root.is_dir():
        print(f"ERROR: site root not found: {site_root}", file=sys.stderr)
        sys.exit(1)

    live_domain = args.live_domain.rstrip("/")

    results = {
        "already_present": [],
        "fetched_ok": [],
        "fetched_not_valid": [],
        "http_errors": [],
        "network_errors": [],
    }

    total = len(ALL_ASSETS)
    for i, (category, rel_path) in enumerate(ALL_ASSETS, 1):
        local_path = site_root / rel_path
        tag = f"[{i}/{total}]"

        if local_path.exists():
            print(f"{tag} ALREADY PRESENT: {rel_path}")
            results["already_present"].append((category, rel_path))
            continue

        if args.dry_run:
            print(f"{tag} WOULD FETCH: {rel_path}")
            continue

        url = f"{live_domain}/{rel_path}"
        try:
            resp = requests.get(url, timeout=20)
        except requests.RequestException as e:
            print(f"{tag} NETWORK ERROR: {rel_path} ({e})")
            results["network_errors"].append((category, rel_path, str(e)))
            time.sleep(args.delay)
            continue

        if resp.status_code != 200:
            print(f"{tag} HTTP {resp.status_code}: {rel_path}")
            results["http_errors"].append((category, rel_path, resp.status_code))
            time.sleep(args.delay)
            continue

        ok, reason = sniff_ok(category, resp.content, resp.headers.get("Content-Type", ""))
        if not ok:
            print(f"{tag} FETCHED BUT INVALID ({reason}): {rel_path}")
            results["fetched_not_valid"].append((category, rel_path, reason))
            time.sleep(args.delay)
            continue

        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(resp.content)
        print(f"{tag} OK ({len(resp.content)} bytes): {rel_path}  [{reason}]")
        results["fetched_ok"].append((category, rel_path, len(resp.content)))
        time.sleep(args.delay)

    lines = ["# CSS-Referenced Assets Fetch Report\n"]
    lines.append(f"Mode: {'DRY RUN' if args.dry_run else 'APPLIED'}\n")
    lines.append(f"Total assets checked: {total}")
    lines.append(f"Already present: {len(results['already_present'])}")
    lines.append(f"Fetched OK: {len(results['fetched_ok'])}")
    lines.append(f"Fetched, not valid: {len(results['fetched_not_valid'])}")
    lines.append(f"HTTP errors: {len(results['http_errors'])}")
    lines.append(f"Network errors: {len(results['network_errors'])}\n")

    for label, key in [
        ("Fetched but not valid (not saved)", "fetched_not_valid"),
        ("HTTP errors (genuinely gone from live site)", "http_errors"),
        ("Network errors", "network_errors"),
        ("Fetched successfully", "fetched_ok"),
    ]:
        items = results[key]
        if items:
            lines.append(f"## {label}\n")
            for row in items:
                if len(row) == 3 and key == "fetched_ok":
                    cat, path, size = row
                    lines.append(f"- [{cat}] {path} ({size} bytes)")
                elif len(row) == 3:
                    cat, path, extra = row
                    lines.append(f"- [{cat}] {path} — {extra}")
                else:
                    lines.append(f"- {row}")
            lines.append("")

    Path(args.report).write_text("\n".join(lines), encoding="utf-8")

    print("\n=== Summary ===")
    print(f"Already present:     {len(results['already_present'])}")
    print(f"Fetched OK:          {len(results['fetched_ok'])}")
    print(f"Fetched, not valid:  {len(results['fetched_not_valid'])}")
    print(f"HTTP errors:         {len(results['http_errors'])}")
    print(f"Network errors:      {len(results['network_errors'])}")
    print(f"Report written to:   {args.report}")


if __name__ == "__main__":
    main()
