#!/usr/bin/env python3
"""
rewrite_next_image_urls.py

Rewrites Next.js image-optimizer proxy URLs of the form:
    /_next/image?url=%2Fimg%2Favatars%2Ffoo.webp&w=384&q=75
into the real decoded local path:
    /img/avatars/foo.webp

across every .html file in a site root. Handles:
  - <img src="...">
  - srcset="..." (comma-separated, each with an optional width/density descriptor)
  - poster="..."
  - inline style="... url(...) ..."
  - <style> blocks containing url(...)

Only rewrites occurrences that match the /_next/image?url= pattern; everything
else in the file (including already-correct real paths, and external/live-domain
links) is left byte-for-byte untouched.

Usage:
    python3 rewrite_next_image_urls.py --site-root SITE_ROOT [--dry-run] [--verify]

Outputs:
    rewrite_report.md  - summary of files changed, occurrences rewritten, and
                          (with --verify) which rewritten target paths are
                          missing on disk.
"""

import argparse
import html
import os
import re
import sys
import urllib.parse
from pathlib import Path

# Matches /_next/image?url=ENCODED&w=NNN&q=NNN  (order of w/q params can vary,
# and the whole thing may be HTML-entity-encoded, i.e. &amp; instead of &)
NEXT_IMAGE_RE = re.compile(
    r"/_next/image\?url=(?P<encoded>[^&\s\"')]+)(?:(?:&amp;|&)[^\s\"')]*)*",
)


def decode_target(encoded: str) -> str:
    """URL-decode the `url=` query param value to get the real local path."""
    return urllib.parse.unquote(encoded)


def rewrite_text(content: str, rewritten_paths: set) -> tuple[str, int]:
    """
    Find every /_next/image?url=... occurrence in `content`, replace it with
    the decoded real path, record the target path in rewritten_paths, and
    return (new_content, count_replaced).
    """
    count = 0

    def _sub(m: re.Match) -> str:
        nonlocal count
        encoded = m.group("encoded")
        real_path = decode_target(encoded)
        # real_path may still contain HTML entities if the source was
        # double-escaped (rare) - normalize defensively.
        real_path_unescaped = html.unescape(real_path)
        count += 1
        rewritten_paths.add(real_path_unescaped)
        return real_path_unescaped

    new_content = NEXT_IMAGE_RE.sub(_sub, content)
    return new_content, count


def process_file(path: Path, dry_run: bool, rewritten_paths: set) -> int:
    original = path.read_text(encoding="utf-8", errors="ignore")
    new_content, count = rewrite_text(original, rewritten_paths)
    if count > 0 and not dry_run:
        path.write_text(new_content, encoding="utf-8")
    return count


def find_html_files(site_root: Path):
    yield from site_root.rglob("*.html")


def verify(site_root: Path, rewritten_paths: set):
    """Check that every rewritten target path actually exists on disk."""
    missing = []
    present = []
    for p in sorted(rewritten_paths):
        # p is a site-relative path like /img/avatars/foo.webp
        # strip query fragments defensively, though there shouldn't be any left
        clean = p.split("?")[0].split("#")[0]
        fs_path = site_root / clean.lstrip("/")
        if fs_path.exists():
            present.append(p)
        else:
            missing.append(p)
    return present, missing


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--site-root", required=True, help="Root of the static site mirror")
    ap.add_argument("--dry-run", action="store_true", help="Report what would change, write nothing")
    ap.add_argument("--verify", action="store_true", help="After rewriting, check rewritten target paths exist on disk")
    ap.add_argument("--report", default="rewrite_report.md", help="Path to write the markdown report")
    args = ap.parse_args()

    site_root = Path(args.site_root).resolve()
    if not site_root.is_dir():
        print(f"ERROR: site root not found: {site_root}", file=sys.stderr)
        sys.exit(1)

    html_files = list(find_html_files(site_root))
    if not html_files:
        print(f"ERROR: no .html files found under {site_root}", file=sys.stderr)
        sys.exit(1)

    rewritten_paths: set = set()
    per_file_counts = {}
    total_occurrences = 0
    files_changed = 0

    for f in html_files:
        count = process_file(f, args.dry_run, rewritten_paths)
        if count > 0:
            per_file_counts[str(f.relative_to(site_root))] = count
            total_occurrences += count
            files_changed += 1

    present, missing = ([], [])
    if args.verify:
        present, missing = verify(site_root, rewritten_paths)

    # --- report ---
    lines = []
    lines.append("# _next/image URL Rewrite Report\n")
    lines.append(f"Mode: {'DRY RUN (no files modified)' if args.dry_run else 'APPLIED'}\n")
    lines.append(f"HTML files scanned: {len(html_files)}")
    lines.append(f"HTML files changed: {files_changed}")
    lines.append(f"Total occurrences rewritten: {total_occurrences}")
    lines.append(f"Distinct real target paths: {len(rewritten_paths)}\n")

    if per_file_counts:
        lines.append("## Occurrences per file\n")
        for fname, c in sorted(per_file_counts.items(), key=lambda x: -x[1]):
            lines.append(f"- {fname}: {c}")
        lines.append("")

    if args.verify:
        lines.append("## Verification of rewritten target paths\n")
        lines.append(f"Present on disk: {len(present)}")
        lines.append(f"MISSING on disk: {len(missing)}\n")
        if missing:
            lines.append("### Missing targets (need fetch_missing_images.py or manual check)\n")
            for m in sorted(missing):
                lines.append(f"- {m}")
            lines.append("")

    report_text = "\n".join(lines)
    Path(args.report).write_text(report_text, encoding="utf-8")

    print(f"Scanned {len(html_files)} HTML files.")
    print(f"Changed {files_changed} files, {total_occurrences} occurrences rewritten.")
    if args.verify:
        print(f"Verify: {len(present)} present, {len(missing)} missing on disk.")
    print(f"Report written to: {args.report}")


if __name__ == "__main__":
    main()
