#!/usr/bin/env python3
"""
static_audit.py — Static audit for a Puppeteer-cloned Next.js site.

Checks (no dependencies beyond Python 3 stdlib):
  1. Broken asset references (<img src>, <video src>, srcset, <link href>,
     <script src>, CSS url(...)) — verifies local existence, flags
     references to the live domain.
  2. Broken internal links (<a href>) — flags live-domain links and
     dead local links.
  5. Absolute-path issues (e.g. /_next/...) — flags paths that only
     resolve if served from domain root, and checks whether the
     corresponding file actually exists at the location that absolute
     path implies relative to SITE_ROOT.

Usage:
    python3 static_audit.py /opt/azurio-clone/site/azuris-nextjs.vercel.app \
        --live-domain azuris-nextjs.vercel.app \
        --report report_static.md

Only stdlib is used (html.parser, urllib.parse, pathlib, re, json) so this
runs anywhere without pip installs.
"""

import argparse
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit, unquote

# ---------------------------------------------------------------------------
# Config: which tags/attrs count as "asset" references vs "link" references
# ---------------------------------------------------------------------------

ASSET_ATTRS = {
    "img": ["src", "srcset", "data-src", "data-srcset"],
    "source": ["src", "srcset"],
    "video": ["src", "poster"],
    "audio": ["src"],
    "link": ["href"],          # stylesheets, preloads, icons, manifest
    "script": ["src"],
    "iframe": ["src"],
    "embed": ["src"],
    "object": ["data"],
}

LINK_ATTRS = {
    "a": ["href"],
    "area": ["href"],
}

CSS_URL_RE = re.compile(r"url\(\s*(['\"]?)([^'\")]+)\1\s*\)", re.IGNORECASE)
SRCSET_SPLIT_RE = re.compile(r"\s*,\s*(?=(?:[^,]*\s+\d)|[^,]*$)")

# File extensions that should never be treated as "pages" when checking
# link targets against the local page mirror (they're handled as assets
# in some templates, e.g. <a href="/file.pdf">).
NON_PAGE_LINK_EXTS = {
    ".pdf", ".zip", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp",
    ".mp4", ".webm", ".mp3", ".wav", ".doc", ".docx", ".xls", ".xlsx",
}

SKIP_SCHEMES = {"mailto", "tel", "javascript", "data", "sms", "fax"}


class RefCollector(HTMLParser):
    """Collects (tag, attr, raw_value, line, col) for every attribute of
    interest, plus inline <style> blocks and style="" attributes for
    CSS url(...) scanning."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.asset_refs = []   # (tag, attr, value)
        self.link_refs = []    # (tag, attr, value)
        self.style_blobs = []  # text content of <style> tags
        self.inline_styles = []  # style="" attr values
        self._in_style = False
        self._style_buf = []

    def handle_starttag(self, tag, attrs):
        attrs_d = dict(attrs)
        tag_l = tag.lower()

        if tag_l in ASSET_ATTRS:
            for attr in ASSET_ATTRS[tag_l]:
                if attr in attrs_d and attrs_d[attr]:
                    self.asset_refs.append((tag_l, attr, attrs_d[attr]))

        if tag_l in LINK_ATTRS:
            for attr in LINK_ATTRS[tag_l]:
                if attr in attrs_d and attrs_d[attr]:
                    self.link_refs.append((tag_l, attr, attrs_d[attr]))

        if "style" in attrs_d and attrs_d["style"]:
            self.inline_styles.append(attrs_d["style"])

        if tag_l == "style":
            self._in_style = True
            self._style_buf = []

        # meta refresh / og:image etc. sometimes carry asset URLs worth a look
        if tag_l == "meta":
            prop = attrs_d.get("property") or attrs_d.get("name")
            if prop in ("og:image", "twitter:image") and attrs_d.get("content"):
                self.asset_refs.append(("meta[%s]" % prop, "content", attrs_d["content"]))

    def handle_endtag(self, tag):
        if tag.lower() == "style" and self._in_style:
            self.style_blobs.append("".join(self._style_buf))
            self._in_style = False

    def handle_data(self, data):
        if self._in_style:
            self._style_buf.append(data)


def parse_srcset(value):
    """Split a srcset attribute into individual URL candidates."""
    parts = SRCSET_SPLIT_RE.split(value.strip())
    urls = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        # each candidate is "<url> <descriptor>?"
        bits = part.split()
        if bits:
            urls.append(bits[0])
    return urls


def is_external(url, live_domain):
    """Return 'live' if it points at the live domain, 'other-external' if
    some other absolute http(s) host, or None if local."""
    split = urlsplit(url)
    if split.scheme in ("http", "https"):
        if live_domain and live_domain in split.netloc:
            return "live"
        return "other-external"
    if split.netloc and not split.scheme:
        # protocol-relative //host/path
        if live_domain and live_domain in split.netloc:
            return "live"
        return "other-external"
    return None


def strip_query_fragment(url):
    split = urlsplit(url)
    return split.path


def resolve_local_path(url, html_file, site_root):
    """
    Resolve a URL reference found inside html_file to a candidate local
    Path, handling:
      - absolute site-root paths ("/_next/foo.js" -> site_root/_next/foo.js)
      - relative paths (resolved against html_file's directory)
      - Next.js-style trailing-slash "pages as directories" with index.html
    Returns (candidate_path, resolution_mode) where resolution_mode is one
    of "absolute-root", "relative", "empty/self".
    """
    path_part = strip_query_fragment(url)
    path_part = unquote(path_part)

    if path_part in ("", "/"):
        return None, "empty/self"

    if path_part.startswith("/"):
        candidate = site_root / path_part.lstrip("/")
        mode = "absolute-root"
    else:
        candidate = (html_file.parent / path_part).resolve()
        mode = "relative"

    return candidate, mode


def file_exists_with_fallbacks(candidate: Path):
    """
    Given a candidate path (which may be a 'page' path with no extension,
    Next.js style), check several plausible on-disk forms a Puppeteer
    crawler might have saved it as:
      - exact file
      - candidate + '.html'
      - candidate / 'index.html'
      - candidate with trailing slash stripped + '.html'
    Returns (exists: bool, actual_path_found: Path|None)
    """
    if candidate.exists() and candidate.is_file():
        return True, candidate
    # try .html suffix (common for crawler-saved "clean URL" pages)
    html_variant = Path(str(candidate) + ".html")
    if html_variant.exists() and html_variant.is_file():
        return True, html_variant
    # try as directory with index.html
    index_variant = candidate / "index.html"
    if index_variant.exists() and index_variant.is_file():
        return True, index_variant
    return False, None


def gather_html_files(site_root: Path):
    return sorted(site_root.rglob("*.html"))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("site_root", help="Path to the site root (folder containing index.html)")
    ap.add_argument("--live-domain", default="azuris-nextjs.vercel.app",
                     help="Live domain to flag references to (default: azuris-nextjs.vercel.app)")
    ap.add_argument("--report", default="report_static.md", help="Output markdown report path")
    ap.add_argument("--json-out", default="report_static.json", help="Output raw JSON findings path")
    args = ap.parse_args()

    site_root = Path(args.site_root).resolve()
    if not site_root.exists():
        print(f"ERROR: site_root does not exist: {site_root}", file=sys.stderr)
        sys.exit(1)

    html_files = gather_html_files(site_root)
    if not html_files:
        print(f"ERROR: no .html files found under {site_root}", file=sys.stderr)
        sys.exit(1)

    # Build the set of "known local pages" for link-target checks.
    # A page is "known" if its relative path (with common variants)
    # corresponds to an actual html file.
    known_pages = set()
    for f in html_files:
        rel = f.relative_to(site_root)
        known_pages.add("/" + str(rel).replace("\\", "/"))
        # also register the "clean URL" form (strip trailing index.html / .html)
        s = str(rel).replace("\\", "/")
        if s.endswith("/index.html"):
            known_pages.add("/" + s[: -len("index.html")])
            known_pages.add("/" + s[: -len("/index.html")])
        elif s == "index.html":
            known_pages.add("/")
        elif s.endswith(".html"):
            known_pages.add("/" + s[: -len(".html")])

    findings = {
        "broken_assets": [],       # asset ref that doesn't resolve locally
        "live_domain_assets": [],  # asset ref still pointing at live domain
        "other_external_assets": [],  # asset ref pointing at some other CDN/host (informational)
        "broken_links": [],       # <a href> to a local page that doesn't exist
        "live_domain_links": [],  # <a href> still pointing at live domain
        "absolute_path_refs": [], # refs using a root-absolute path (informational + resolution check)
        "css_url_findings": [],   # url(...) refs inside <style> / style="" that are broken or live-domain
        "srcset_findings": [],    # specifically flagged srcset entries (broken or live-domain)
        "stats": {
            "html_files_scanned": len(html_files),
        },
    }

    total_asset_refs = 0
    total_link_refs = 0

    for html_file in html_files:
        rel_html = "/" + str(html_file.relative_to(site_root)).replace("\\", "/")
        try:
            raw = html_file.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            print(f"WARN: could not read {html_file}: {e}", file=sys.stderr)
            continue

        parser = RefCollector()
        try:
            parser.feed(raw)
        except Exception as e:
            print(f"WARN: HTML parse issue in {html_file}: {e}", file=sys.stderr)

        # ---- asset refs (img/video/link/script/etc.) ----
        for tag, attr, value in parser.asset_refs:
            total_asset_refs += 1
            candidates = []
            if attr in ("srcset", "data-srcset"):
                for u in parse_srcset(value):
                    candidates.append(("srcset-entry", u))
            else:
                candidates.append((attr, value))

            for sub_attr, url in candidates:
                url = url.strip()
                if not url or url.startswith("#"):
                    continue
                split = urlsplit(url)
                if split.scheme in SKIP_SCHEMES:
                    continue

                ext_kind = is_external(url, args.live_domain)
                if ext_kind == "live":
                    entry = {
                        "file": rel_html, "tag": tag, "attr": attr,
                        "raw_attr_value": value, "url": url,
                    }
                    findings["live_domain_assets"].append(entry)
                    if attr in ("srcset", "data-srcset"):
                        findings["srcset_findings"].append({**entry, "issue": "live-domain-in-srcset"})
                    continue
                elif ext_kind == "other-external":
                    findings["other_external_assets"].append({
                        "file": rel_html, "tag": tag, "attr": attr, "url": url,
                    })
                    continue

                # local reference — check existence
                candidate, mode = resolve_local_path(url, html_file, site_root)
                if candidate is None:
                    continue
                exists, actual = file_exists_with_fallbacks(candidate)
                if not exists:
                    entry = {
                        "file": rel_html, "tag": tag, "attr": attr,
                        "raw_attr_value": value, "url": url,
                        "resolved_candidate": str(candidate.relative_to(site_root)) if str(candidate).startswith(str(site_root)) else str(candidate),
                        "resolution_mode": mode,
                    }
                    findings["broken_assets"].append(entry)
                    if attr in ("srcset", "data-srcset"):
                        findings["srcset_findings"].append({**entry, "issue": "broken-in-srcset"})
                elif mode == "absolute-root":
                    findings["absolute_path_refs"].append({
                        "file": rel_html, "tag": tag, "attr": attr, "url": url,
                        "resolves_ok_from_site_root": True,
                    })

        # ---- link refs (<a href>) ----
        for tag, attr, value in parser.link_refs:
            total_link_refs += 1
            url = value.strip()
            if not url or url.startswith("#"):
                continue
            split = urlsplit(url)
            if split.scheme in SKIP_SCHEMES:
                continue

            ext_kind = is_external(url, args.live_domain)
            if ext_kind == "live":
                findings["live_domain_links"].append({
                    "file": rel_html, "tag": tag, "attr": attr, "url": url,
                })
                continue
            elif ext_kind == "other-external":
                continue  # genuinely external (e.g. social links) — not our concern

            # local link — normalize and check against known_pages, with
            # fallback to filesystem check (covers assets linked via <a>,
            # e.g. PDF downloads)
            path_only = strip_query_fragment(url)
            path_only = unquote(path_only)
            ext = Path(path_only).suffix.lower()

            if path_only in known_pages:
                if path_only.startswith("/") and path_only.rstrip("/") + "/" in known_pages:
                    pass
                continue

            # try trailing-slash-insensitive match
            alt1 = path_only if path_only.endswith("/") else path_only + "/"
            alt2 = path_only.rstrip("/")
            if alt1 in known_pages or alt2 in known_pages or (alt2 + "/index.html") in ("/" + p.lstrip("/") for p in known_pages):
                continue

            if ext in NON_PAGE_LINK_EXTS:
                # treat as asset-style existence check instead
                candidate, mode = resolve_local_path(url, html_file, site_root)
                if candidate is not None:
                    exists, _ = file_exists_with_fallbacks(candidate)
                    if not exists:
                        findings["broken_links"].append({
                            "file": rel_html, "tag": tag, "attr": attr, "url": url,
                            "kind": "non-page-asset-link", "resolution_mode": mode,
                        })
                continue

            # otherwise, treat as a page link and check filesystem directly
            candidate, mode = resolve_local_path(url, html_file, site_root)
            if candidate is None:
                continue
            exists, actual = file_exists_with_fallbacks(candidate)
            if not exists:
                findings["broken_links"].append({
                    "file": rel_html, "tag": tag, "attr": attr, "url": url,
                    "kind": "page-link", "resolution_mode": mode,
                    "resolved_candidate": str(candidate.relative_to(site_root)) if str(candidate).startswith(str(site_root)) else str(candidate),
                })
            elif mode == "absolute-root":
                findings["absolute_path_refs"].append({
                    "file": rel_html, "tag": "a", "attr": "href", "url": url,
                    "resolves_ok_from_site_root": True,
                })

        # ---- CSS url(...) refs: inline <style> blocks and style="" attrs ----
        css_blobs = list(parser.style_blobs) + list(parser.inline_styles)
        for blob in css_blobs:
            for m in CSS_URL_RE.finditer(blob):
                url = m.group(2).strip()
                if not url or url.startswith("data:"):
                    continue
                ext_kind = is_external(url, args.live_domain)
                if ext_kind == "live":
                    findings["css_url_findings"].append({
                        "file": rel_html, "url": url, "issue": "live-domain",
                    })
                    continue
                elif ext_kind == "other-external":
                    continue
                candidate, mode = resolve_local_path(url, html_file, site_root)
                if candidate is None:
                    continue
                exists, _ = file_exists_with_fallbacks(candidate)
                if not exists:
                    findings["css_url_findings"].append({
                        "file": rel_html, "url": url, "issue": "broken",
                        "resolution_mode": mode,
                    })

    # Also scan standalone .css files on disk for url(...) refs
    css_files = sorted(site_root.rglob("*.css"))
    for css_file in css_files:
        rel_css = "/" + str(css_file.relative_to(site_root)).replace("\\", "/")
        try:
            raw = css_file.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for m in CSS_URL_RE.finditer(raw):
            url = m.group(2).strip()
            if not url or url.startswith("data:"):
                continue
            ext_kind = is_external(url, args.live_domain)
            if ext_kind == "live":
                findings["css_url_findings"].append({
                    "file": rel_css, "url": url, "issue": "live-domain", "source": "css-file",
                })
                continue
            elif ext_kind == "other-external":
                continue
            candidate, mode = resolve_local_path(url, css_file, site_root)
            if candidate is None:
                continue
            exists, _ = file_exists_with_fallbacks(candidate)
            if not exists:
                findings["css_url_findings"].append({
                    "file": rel_css, "url": url, "issue": "broken",
                    "resolution_mode": mode, "source": "css-file",
                })

    findings["stats"]["total_asset_refs_scanned"] = total_asset_refs
    findings["stats"]["total_link_refs_scanned"] = total_link_refs
    findings["stats"]["css_files_scanned"] = len(css_files)

    # Write JSON
    json_path = Path(args.json_out)
    json_path.write_text(json.dumps(findings, indent=2), encoding="utf-8")

    # Write Markdown report
    write_markdown_report(findings, Path(args.report), site_root, args.live_domain)

    print(f"Scanned {len(html_files)} HTML files, {len(css_files)} CSS files.")
    print(f"Report written to: {args.report}")
    print(f"Raw JSON written to: {args.json_out}")
    print()
    print("=== Summary ===")
    print(f"Broken asset refs:        {len(findings['broken_assets'])}")
    print(f"Live-domain asset refs:   {len(findings['live_domain_assets'])}")
    print(f"  (of which in srcset):   {sum(1 for x in findings['srcset_findings'] if x['issue']=='live-domain-in-srcset')}")
    print(f"Broken srcset entries:    {sum(1 for x in findings['srcset_findings'] if x['issue']=='broken-in-srcset')}")
    print(f"Broken internal links:    {len(findings['broken_links'])}")
    print(f"Live-domain links:        {len(findings['live_domain_links'])}")
    print(f"CSS url() issues:         {len(findings['css_url_findings'])}")
    print(f"Absolute-root-path refs:  {len(findings['absolute_path_refs'])} (informational)")


def write_markdown_report(findings, out_path: Path, site_root: Path, live_domain: str):
    lines = []
    lines.append(f"# Static Audit Report\n")
    lines.append(f"Site root: `{site_root}`  \nLive domain flagged: `{live_domain}`\n")
    s = findings["stats"]
    lines.append("## Stats\n")
    lines.append(f"- HTML files scanned: {s['html_files_scanned']}")
    lines.append(f"- CSS files scanned: {s['css_files_scanned']}")
    lines.append(f"- Total asset refs scanned: {s['total_asset_refs_scanned']}")
    lines.append(f"- Total link refs scanned: {s['total_link_refs_scanned']}\n")

    def section(title, items, cols):
        lines.append(f"## {title} ({len(items)})\n")
        if not items:
            lines.append("_None found._\n")
            return
        lines.append("| " + " | ".join(cols) + " |")
        lines.append("|" + "|".join(["---"] * len(cols)) + "|")
        for it in items:
            row = [str(it.get(c, "")).replace("|", "\\|") for c in cols]
            lines.append("| " + " | ".join(row) + " |")
        lines.append("")

    section(
        "1a. Broken Asset References (file not found locally)",
        findings["broken_assets"],
        ["file", "tag", "attr", "url", "resolved_candidate", "resolution_mode"],
    )
    section(
        "1b. Assets Still Pointing at Live Domain",
        findings["live_domain_assets"],
        ["file", "tag", "attr", "url"],
    )
    section(
        "1c. srcset-specific Findings",
        findings["srcset_findings"],
        ["file", "issue", "url", "raw_attr_value"],
    )
    section(
        "1d. CSS url(...) Issues (inline styles + .css files)",
        findings["css_url_findings"],
        ["file", "issue", "url", "source"],
    )
    section(
        "1e. Other External Asset Hosts (informational — likely legitimate CDNs)",
        findings["other_external_assets"][:100],
        ["file", "tag", "attr", "url"],
    )
    section(
        "2a. Broken Internal Links (dead post-clone)",
        findings["broken_links"],
        ["file", "tag", "url", "kind", "resolved_candidate"],
    )
    section(
        "2b. Links Still Pointing at Live Domain",
        findings["live_domain_links"],
        ["file", "tag", "url"],
    )
    section(
        "5. Absolute Root-Path References (e.g. /_next/...) — resolve OK from site_root, but WILL break if served from a subpath",
        findings["absolute_path_refs"][:200],
        ["file", "tag", "attr", "url"],
    )

    out_path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
