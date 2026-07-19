#!/usr/bin/env python3
"""
fetch_missing_images.py — Recover the 271 original images that the
Puppeteer crawler failed to capture correctly.

Root cause (confirmed via audit): the crawler captured Next.js's
*optimizer proxy* responses (/_next/image?url=...&w=...&q=75) instead of
the real underlying source images, saving them under mangled/truncated
filenames with a wrong .html extension in _next/image/. Those files
turned out to be genuine (but unrecoverable-by-name) WebP bytes — the
truncated filenames collide across multiple distinct source images
(verified: all six 300x300_ava-0N.webp avatars produce the identical
truncated name), so they can't be reliably renamed back.

Fix: skip the optimizer entirely and fetch each real source image
directly from its stable, non-proxied path on the live domain, e.g.
  https://azuris-nextjs.vercel.app/img/avatars/300x300_ava-01.webp
This is the original file Next.js's <Image> component wraps — it exists
independently of the ?w=&q= resizing proxy and doesn't have the
filename-collision problem.

Each downloaded file is verified with `imghdr`/signature-sniffing before
being kept, so we don't repeat the earlier mistake of trusting a 200
response or a plausible-looking file without checking its actual bytes
(a soft-404 error page saved with an image extension would corrupt the
mirror silently otherwise).

Usage:
    python3 fetch_missing_images.py \
        --site-root /opt/azurio-clone/site/azuris-nextjs.vercel.app \
        --live-domain https://azuris-nextjs.vercel.app \
        --paths-file underlying_paths_final.txt \
        --report fetch_report.md

If --paths-file is omitted, the script re-derives the path list directly
from report_static.md (pass --static-report to point at it), so you
don't have to keep the intermediate file around.
"""

import argparse
import re
import sys
import time
from pathlib import Path
from urllib.parse import unquote, urljoin

# Recognized file signatures (magic bytes) for the image types this site
# uses. We check actual bytes, not the HTTP status code or content-type
# header alone — both can lie (e.g. a 200 response body that's actually
# an HTML error/soft-404 page).
SIGNATURES = {
    b"RIFF": "webp-or-wav",  # further disambiguated below (need WEBP at offset 8)
    b"\x89PNG\r\n\x1a\n": "png",
    b"\xff\xd8\xff": "jpeg",
    b"GIF87a": "gif",
    b"GIF89a": "gif",
    b"<svg": "svg",
    b"<?xml": "svg-xml-decl",
}


def sniff_image_type(data: bytes):
    if len(data) < 12:
        return None
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    stripped = data.lstrip()[:200].lower()
    if stripped.startswith(b"<svg") or (stripped.startswith(b"<?xml") and b"<svg" in data[:500].lower()):
        return "svg"
    return None


def looks_like_html_error(data: bytes) -> bool:
    head = data[:300].lower()
    return b"<!doctype html" in head or b"<html" in head


def load_paths_from_static_report(report_path: Path):
    with open(report_path, encoding="utf-8") as f:
        lines = f.readlines()
    section = []
    in_section = False
    for line in lines:
        if line.startswith("## 1a."):
            in_section = True
            continue
        if line.startswith("## 1b."):
            break
        if in_section and line.startswith("|") and not line.startswith("|---") and "file | tag" not in line:
            section.append(line.strip())

    underlying = set()
    for row in section:
        parts = [p.strip() for p in row.split("|")[1:-1]]
        if len(parts) < 6:
            continue
        url = parts[3]
        if url.startswith("/_next/image?url="):
            m = re.search(r"url=([^&]+)", url)
            if m:
                underlying.add(unquote(m.group(1)))
    return sorted(underlying)


def load_paths_from_file(paths_file: Path):
    with open(paths_file, encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--site-root", required=True, help="Local site root to save recovered images into")
    ap.add_argument("--live-domain", default="https://azuris-nextjs.vercel.app",
                     help="Live domain to fetch original images from")
    ap.add_argument("--paths-file", help="Text file, one image path per line (e.g. /img/avatars/300x300_ava-01.webp)")
    ap.add_argument("--static-report", help="Path to report_static.md, used to derive the path list if --paths-file is not given")
    ap.add_argument("--report", default="fetch_report.md")
    ap.add_argument("--dry-run", action="store_true", help="Show what would be fetched/written without making any network requests or writing files")
    ap.add_argument("--delay", type=float, default=0.3, help="Seconds to sleep between requests (be polite to the live server)")
    ap.add_argument("--timeout", type=float, default=20.0)
    args = ap.parse_args()

    site_root = Path(args.site_root).resolve()
    if not site_root.exists():
        print(f"ERROR: site root does not exist: {site_root}", file=sys.stderr)
        sys.exit(1)

    if args.paths_file:
        paths = load_paths_from_file(Path(args.paths_file))
    elif args.static_report:
        paths = load_paths_from_static_report(Path(args.static_report))
    else:
        print("ERROR: pass either --paths-file or --static-report", file=sys.stderr)
        sys.exit(1)

    print(f"Loaded {len(paths)} image paths to fetch.")

    if not args.dry_run:
        try:
            import requests
        except ImportError:
            print("ERROR: this script needs the 'requests' library. Install with:\n"
                  "  pip install requests --break-system-packages", file=sys.stderr)
            sys.exit(1)
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; site-mirror-repair/1.0)"
        })

    results = {
        "already_present": [],
        "fetched_ok": [],
        "fetched_but_not_image": [],  # got a 200 but bytes don't look like a real image (likely a soft-404/error page)
        "http_error": [],             # non-200 status
        "network_error": [],          # timeout, DNS, connection refused, etc.
        "extension_mismatch": [],     # real image, but sniffed type doesn't match the file's extension
    }

    for i, rel_path in enumerate(paths, 1):
        rel_path = rel_path if rel_path.startswith("/") else "/" + rel_path
        local_path = site_root / rel_path.lstrip("/")

        if local_path.exists() and local_path.stat().st_size > 0:
            results["already_present"].append(rel_path)
            continue

        url = urljoin(args.live_domain.rstrip("/") + "/", rel_path.lstrip("/"))

        if args.dry_run:
            print(f"[{i}/{len(paths)}] WOULD FETCH: {url} -> {local_path}")
            continue

        try:
            resp = session.get(url, timeout=args.timeout)
        except Exception as e:
            print(f"[{i}/{len(paths)}] NETWORK ERROR: {url} ({e})")
            results["network_error"].append({"path": rel_path, "url": url, "error": str(e)})
            time.sleep(args.delay)
            continue

        if resp.status_code != 200:
            print(f"[{i}/{len(paths)}] HTTP {resp.status_code}: {url}")
            results["http_error"].append({"path": rel_path, "url": url, "status": resp.status_code})
            time.sleep(args.delay)
            continue

        data = resp.content
        sniffed = sniff_image_type(data)

        if sniffed is None:
            is_html_err = looks_like_html_error(data)
            print(f"[{i}/{len(paths)}] NOT AN IMAGE ({'looks like HTML/error page' if is_html_err else 'unrecognized bytes'}): {url}")
            results["fetched_but_not_image"].append({
                "path": rel_path, "url": url, "size": len(data),
                "looks_like_html_error": is_html_err,
                "first_bytes_hex": data[:16].hex(),
            })
            time.sleep(args.delay)
            continue

        expected_ext = local_path.suffix.lower().lstrip(".")
        ext_map = {"jpeg": "jpg"}  # tolerate .jpg vs jpeg naming
        normalized_expected = ext_map.get(expected_ext, expected_ext)
        normalized_sniffed = ext_map.get(sniffed, sniffed)
        if normalized_expected and normalized_expected != normalized_sniffed and not (
            normalized_expected == "jpg" and normalized_sniffed == "jpeg"
        ):
            results["extension_mismatch"].append({
                "path": rel_path, "url": url, "expected_ext": expected_ext, "sniffed_type": sniffed,
            })
            # still save it — the bytes are real, extension mismatch is just a flag to review

        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(data)
        results["fetched_ok"].append({"path": rel_path, "url": url, "size": len(data), "sniffed_type": sniffed})
        print(f"[{i}/{len(paths)}] OK ({sniffed}, {len(data)} bytes): {rel_path}")

        time.sleep(args.delay)

    # ---- report ----
    lines = []
    lines.append("# Image Recovery Report\n")
    lines.append(f"Site root: `{site_root}`  \nLive domain: `{args.live_domain}`\n")
    lines.append(f"Total paths considered: {len(paths)}\n")
    lines.append(f"- Already present (skipped): {len(results['already_present'])}")
    lines.append(f"- Fetched successfully: {len(results['fetched_ok'])}")
    lines.append(f"- Fetched but NOT valid image bytes (likely dead source, needs manual check): {len(results['fetched_but_not_image'])}")
    lines.append(f"- HTTP errors (404/etc from live domain): {len(results['http_error'])}")
    lines.append(f"- Network errors: {len(results['network_error'])}")
    lines.append(f"- Extension mismatches (saved anyway, flagged for review): {len(results['extension_mismatch'])}\n")

    def section(title, items, cols):
        lines.append(f"## {title} ({len(items)})\n")
        if not items:
            lines.append("_None._\n")
            return
        lines.append("| " + " | ".join(cols) + " |")
        lines.append("|" + "|".join(["---"] * len(cols)) + "|")
        for it in items:
            if isinstance(it, str):
                row = [it]
            else:
                row = [str(it.get(c, "")) for c in cols]
            lines.append("| " + " | ".join(row) + " |")
        lines.append("")

    section("Fetched but not valid images (needs manual check)", results["fetched_but_not_image"],
             ["path", "url", "size", "looks_like_html_error"])
    section("HTTP errors from live domain", results["http_error"], ["path", "url", "status"])
    section("Network errors", results["network_error"], ["path", "url", "error"])
    section("Extension mismatches (saved anyway)", results["extension_mismatch"],
             ["path", "url", "expected_ext", "sniffed_type"])
    section("Successfully fetched", results["fetched_ok"][:300], ["path", "size", "sniffed_type"])

    Path(args.report).write_text("\n".join(lines), encoding="utf-8")

    print()
    print("=== Summary ===")
    print(f"Already present:        {len(results['already_present'])}")
    print(f"Fetched OK:             {len(results['fetched_ok'])}")
    print(f"Fetched, not an image:  {len(results['fetched_but_not_image'])}")
    print(f"HTTP errors:            {len(results['http_error'])}")
    print(f"Network errors:         {len(results['network_error'])}")
    print(f"Extension mismatches:   {len(results['extension_mismatch'])}")
    print(f"\nReport written to: {args.report}")


if __name__ == "__main__":
    main()
