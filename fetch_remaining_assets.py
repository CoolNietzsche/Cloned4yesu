#!/usr/bin/env python3
"""
fetch_remaining_assets.py

Fetches the last set of genuinely-missing static assets identified by
report_static.md's "1a. Broken Asset References" section, after the
_next/image proxy-URL rewrite already resolved the bulk of the count.

Covers four categories, each with different risk/handling:

  1. FAVICON      - /favicon.ico (hashed query string in HTML, plain file on disk)
  2. JS CHUNK      - /_next/static/chunks/<hash>.js  (hash mismatch = possible
                     different build than the crawled HTML; fetched under the
                     REFERENCED filename but flagged loudly for manual diff review)
  3. VIDEOS        - /video/*.webm, *.mp4, *.ogv  (crawler missed alternate
                      <source> candidates in multi-source <video> tags)
  4. TECH ICONS    - /img/tech/icon-*.svg  (whole directory missing)

Uses the same safe-fetch discipline as fetch_missing_images.py:
  - Only writes a file if the response is a real 200 AND the bytes plausibly
    match the expected type (not an HTML soft-404 disguised as the asset).
  - Never overwrites a file that's already present locally.
  - Produces a report with explicit categories for manual follow-up.

Usage:
    pip install requests --break-system-packages
    python3 fetch_remaining_assets.py \
        --site-root /opt/azurio-clone/site/azuris-nextjs.vercel.app \
        --live-domain https://azuris-nextjs.vercel.app \
        --report fetch_remaining_report.md \
        [--dry-run] [--delay 0.3]
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

# --- Asset manifest: (category, local_relative_path, live_relative_path) ---
# live_relative_path is what we request from the live domain.
# local_relative_path is where we save it (may differ for the JS chunk case).

FAVICON = [
    ("favicon", "favicon.ico", "favicon.ico"),
]

JS_CHUNKS = [
    # Referenced hash in HTML - fetch under this exact name so HTML refs resolve,
    # but flag for manual review since the hash mismatch implies a different build.
    ("js_chunk", "_next/static/chunks/03~yq9q893hmn.js", "_next/static/chunks/03~yq9q893hmn.js"),
]

VIDEOS = [
    ("video", f"video/{name}", f"video/{name}")
    for name in [
        "900x1280_menu.webm",
        "360x225_hero-01.webm",
        "1280x720_stone-geometry.mp4",
        "1280x720_stone-geometry.webm",
        "640x360_stone-geometry.webm",
        "640x360_bw-geometry.webm",
        "1280x720_hero-06.webm",
        "1280x720_hero-02.webm",
        "1280x720_bus.mp4",
        "1280x720_bus.webm",
        "1280x720_hero-09.webm",
        "1920x660_cta.webm",
        "1920x660_cta.ogv",
        "400x225_hero-10.webm",
        "1280x720_hero-03.webm",
        "1280x720_bw-geometry.webm",
        "1280x720_video-05.webm",
        "1280x720_tree.webm",
    ]
]

TECH_ICONS = [
    ("tech_icon", f"img/tech/{name}", f"img/tech/{name}")
    for name in [
        "icon-figma.svg",
        "icon-photoshop.svg",
        "icon-illustrator.svg",
        "icon-sketch.svg",
        "icon-blender.svg",
        "icon-midjourney.svg",
        "icon-unicorn.svg",
        "icon-notion.svg",
    ]
]

ALL_ASSETS = FAVICON + JS_CHUNKS + VIDEOS + TECH_ICONS

# Magic-byte / content sniffing per category so we never save a soft-404 HTML
# page as if it were the real asset.
def sniff_ok(category: str, content: bytes, content_type: str) -> tuple[bool, str]:
    if len(content) < 16:
        return False, "response too short to be a real asset"

    head = content[:16]
    ctype = (content_type or "").lower()

    # Universal soft-404 guard: reject if it looks like an HTML error page
    lowered_start = content[:500].lower()
    if b"<!doctype html" in lowered_start or b"<html" in lowered_start:
        return False, "looks like an HTML page (soft-404), not the real asset"

    if category == "favicon":
        # ICO magic: 00 00 01 00  (or PNG-based favicons: 89 50 4E 47)
        if head[:4] == b"\x00\x00\x01\x00" or head[:8] == b"\x89PNG\r\n\x1a\n":
            return True, "ok"
        return False, f"doesn't look like ICO/PNG (content-type: {ctype})"

    if category == "js_chunk":
        # JS is text; just make sure it's not binary garbage or HTML (already checked above)
        try:
            content[:2000].decode("utf-8")
            return True, "ok (text/js) - VERIFY MANUALLY: hash mismatch vs local build"
        except UnicodeDecodeError:
            return False, "not valid UTF-8 text, unlikely to be real JS"

    if category == "video":
        # mp4: ftyp box a few bytes in; webm/mkv: EBML header 1A 45 DF A3; ogv: OggS
        if b"ftyp" in content[:32] or head[:4] == b"\x1a\x45\xdf\xa3" or head[:4] == b"OggS":
            return True, "ok"
        return False, f"doesn't look like mp4/webm/ogv (content-type: {ctype})"

    if category == "tech_icon":
        # SVG is text/XML
        lowered = content[:200].lower()
        if b"<svg" in lowered or b"<?xml" in lowered:
            return True, "ok"
        return False, f"doesn't look like SVG (content-type: {ctype})"

    return False, "unknown category"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--site-root", required=True)
    ap.add_argument("--live-domain", required=True, help="e.g. https://azuris-nextjs.vercel.app")
    ap.add_argument("--report", default="fetch_remaining_report.md")
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
        "manual_review": [],  # js chunk always lands here even on success
    }

    total = len(ALL_ASSETS)
    for i, (category, local_rel, live_rel) in enumerate(ALL_ASSETS, 1):
        local_path = site_root / local_rel
        tag = f"[{i}/{total}]"

        if local_path.exists():
            print(f"{tag} ALREADY PRESENT: {local_rel}")
            results["already_present"].append((category, local_rel))
            continue

        if args.dry_run:
            print(f"{tag} WOULD FETCH: {live_rel}  ->  {local_rel}")
            continue

        url = f"{live_domain}/{live_rel}"
        try:
            resp = requests.get(url, timeout=20)
        except requests.RequestException as e:
            print(f"{tag} NETWORK ERROR: {live_rel} ({e})")
            results["network_errors"].append((category, live_rel, str(e)))
            time.sleep(args.delay)
            continue

        if resp.status_code != 200:
            print(f"{tag} HTTP {resp.status_code}: {live_rel}")
            results["http_errors"].append((category, live_rel, resp.status_code))
            time.sleep(args.delay)
            continue

        ok, reason = sniff_ok(category, resp.content, resp.headers.get("Content-Type", ""))
        if not ok:
            print(f"{tag} FETCHED BUT INVALID ({reason}): {live_rel}")
            results["fetched_not_valid"].append((category, live_rel, reason))
            time.sleep(args.delay)
            continue

        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(resp.content)
        print(f"{tag} OK ({len(resp.content)} bytes): {local_rel}  [{reason}]")
        results["fetched_ok"].append((category, local_rel, len(resp.content)))
        if category == "js_chunk":
            results["manual_review"].append(
                (category, local_rel, "Hash in filename does not match any locally-crawled chunk. "
                                       "This file may belong to a different site build/deploy than "
                                       "the HTML that references it. Diff against known-working chunks "
                                       "before trusting it in production.")
            )

        time.sleep(args.delay)

    # --- report ---
    lines = ["# Remaining Assets Fetch Report\n"]
    lines.append(f"Mode: {'DRY RUN' if args.dry_run else 'APPLIED'}\n")
    lines.append(f"Total assets checked: {total}")
    lines.append(f"Already present: {len(results['already_present'])}")
    lines.append(f"Fetched OK: {len(results['fetched_ok'])}")
    lines.append(f"Fetched, not valid: {len(results['fetched_not_valid'])}")
    lines.append(f"HTTP errors: {len(results['http_errors'])}")
    lines.append(f"Network errors: {len(results['network_errors'])}\n")

    if results["manual_review"]:
        lines.append("## ⚠️ MANUAL REVIEW REQUIRED\n")
        for category, path, note in results["manual_review"]:
            lines.append(f"- **{path}** ({category}): {note}")
        lines.append("")

    if results["fetched_not_valid"]:
        lines.append("## Fetched but not a valid asset (not saved)\n")
        for category, url, reason in results["fetched_not_valid"]:
            lines.append(f"- [{category}] {url} — {reason}")
        lines.append("")

    if results["http_errors"]:
        lines.append("## HTTP errors (asset genuinely gone from live site too)\n")
        for category, url, code in results["http_errors"]:
            lines.append(f"- [{category}] {url} — HTTP {code}")
        lines.append("")

    if results["network_errors"]:
        lines.append("## Network errors\n")
        for category, url, err in results["network_errors"]:
            lines.append(f"- [{category}] {url} — {err}")
        lines.append("")

    if results["fetched_ok"]:
        lines.append("## Fetched successfully\n")
        for category, path, size in results["fetched_ok"]:
            lines.append(f"- [{category}] {path} ({size} bytes)")
        lines.append("")

    Path(args.report).write_text("\n".join(lines), encoding="utf-8")

    print("\n=== Summary ===")
    print(f"Already present:     {len(results['already_present'])}")
    print(f"Fetched OK:          {len(results['fetched_ok'])}")
    print(f"Fetched, not valid:  {len(results['fetched_not_valid'])}")
    print(f"HTTP errors:         {len(results['http_errors'])}")
    print(f"Network errors:      {len(results['network_errors'])}")
    print(f"Report written to:   {args.report}")
    if results["manual_review"]:
        print(f"\n⚠️  {len(results['manual_review'])} item(s) need manual review — see report.")


if __name__ == "__main__":
    main()
