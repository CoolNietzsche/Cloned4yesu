# Azurio Static Clone — Audit & Repair Toolkit

## What this repo is

This repo contains a **static clone of a Next.js website**, produced by a Puppeteer
crawler that rendered each page and saved the resulting HTML plus network assets.

**This is NOT the original framework source.** There is:
- no live Next.js routing
- no React components
- no build step

It is a flat, file-based mirror of what the live site rendered to at crawl time.
Alongside the mirror, this repo contains a set of **audit and repair scripts**
written to find and fix defects that the cloning process introduced (broken
asset references, missing files, stale proxy URLs, etc).

- **Repo root:** `/opt/azurio-clone`
- **Site root (the actual mirrored site):** `/opt/azurio-clone/site/azuris-nextjs.vercel.app`
- **Live domain the site was cloned from:** `azuris-nextjs.vercel.app`
- **Source repo:** https://github.com/CoolNietzsche/staginglanding

If you are an AI agent picking this up: **read this whole file before touching
anything.** It tells you what's already been fixed, what tools exist to fix
the rest, and what's still broken.

---

## Why a clone like this breaks things

A Puppeteer crawler saves whatever HTML Chrome renders and whatever assets
Chrome actually requests over the network. It does **not** understand:

- Next.js's `/_next/image?url=...&w=...&q=...` image-optimizer proxy — the
  crawler may or may not have saved a request against that exact query
  string, and even when it did, other pages reference the *same underlying
  image* through different `w=`/`q=` query strings that were never crawled.
- Multi-`<source>` `<video>` tags — browsers only request the first source
  format they support, so alternate `<source>` candidates (e.g. `.webm`
  fallback when `.mp4` already loaded) are frequently never fetched at all.
- Build-hash drift — if the live site was re-deployed between when different
  pages were crawled, you can end up with HTML referencing a JS/CSS chunk
  hash that doesn't match any file actually saved locally, because that
  chunk belongs to a different deploy.
- Query-string-suffixed static files (e.g. `/favicon.ico?favicon.<hash>.ico`)
  where the HTML keeps the query string but the file was saved without it,
  or wasn't saved at all.

Every script in this repo exists to detect or repair one of these categories.

---

## Tooling inventory

All scripts live in the repo root (`/opt/azurio-clone`) unless noted. Run
everything from there.

### 1. `static_audit.py` — the main diagnostic (read-only, no writes)

Pure Python, stdlib only. Scans every `.html` and `.css` file under the site
root and reports:

- **1a. Broken asset references** — `<img src>`, `<video src>`, `srcset`,
  `<link href>`, `<script src>`, CSS `url()` — anything that points at a
  local path that doesn't actually exist on disk.
- **1b. Assets still pointing at the live domain** instead of a local path.
- **1c. srcset-specific findings** (srcset is commonly missed by naive
  crawlers/scripts, so it gets its own breakdown).
- **1d. CSS `url()` issues** — broken references inside `.css` files and
  inline `style="..."` attributes.
- **1e. Other external asset hosts** (informational — e.g. legitimate CDNs).
- **2a. Broken internal links** — `<a href>` to pages that don't exist
  locally (dead post-clone).
- **2b. Links still pointing at the live domain** that should be local.
- **5. Absolute root-path references** (e.g. `/_next/...`, `/img/...`) —
  these resolve fine when the site is served from domain root, but will
  break if the site is ever served from a subpath. Informational only.

```bash
python3 static_audit.py /opt/azurio-clone/site/azuris-nextjs.vercel.app \
    --live-domain azuris-nextjs.vercel.app \
    --report report_static.md
```

Outputs `report_static.md` (human-readable) and `report_static.json` (raw
data, useful if you're writing another script against the findings).

**Always re-run this after any repair step** to confirm the fix actually
moved the numbers, and to catch regressions.

### 2. `runtime_audit.py` — Playwright-based runtime checker

Serves the site locally and crawls key page templates (not the full 578
pages — see "Scope decisions" below) in a headless browser, capturing:

- Console errors
- Failed network requests (404s, CORS errors, mixed content warnings)
- Whether JS-dependent UI (menus, sliders, video backgrounds, cursor
  effects, form handlers) actually functions against the local asset set,
  including **silent failures** (no console error, but the effect doesn't
  work) — these are the dangerous ones because static analysis alone can't
  catch them.

Requires Playwright (already validated as available in the dev sandbox this
was built in; confirm it's installed in your environment — `pip install
playwright --break-system-packages && playwright install chromium` if not).

### 3. `fetch_missing_images.py` — safe image fetcher

Reads the broken `/_next/image?url=...` references out of an existing
`report_static.md`, fetches each one's real underlying path from the live
domain, and writes it to disk **only if the response genuinely sniffs as an
image** (correct magic bytes). This protects against the single most
dangerous failure mode in this kind of repair: silently saving a soft-404
HTML error page as if it were a real `.webp`/`.jpg`, which corrupts the
mirror in a way that's hard to detect later.

Classifies every fetch into one of six outcomes:

| Outcome | Behavior |
|---|---|
| Already present locally | Skipped, no network call made |
| Valid image, correct extension | Fetched & saved |
| 200 response, junk bytes | Skipped, not saved, flagged |
| 200 response, HTML error page disguised as image | Skipped, not saved, flagged as HTML-like |
| Real 404 from server | Skipped, not saved, logged as HTTP error |
| Valid image bytes but mismatched extension | Saved (bytes are real) + flagged for manual review |

```bash
pip install requests --break-system-packages

python3 fetch_missing_images.py \
    --site-root /opt/azurio-clone/site/azuris-nextjs.vercel.app \
    --live-domain https://azuris-nextjs.vercel.app \
    --static-report report_static.md \
    --report fetch_report.md
```

Use `--dry-run` first to preview without making requests. Default 0.3s
delay between requests (adjustable with `--delay`) to be polite to the live
domain.

**Status: already run successfully.** All 271 originally-missing images
were fetched with zero failures.

### 4. `rewrite_next_image_urls.py` — proxy-URL rewriter

Fetching the missing image bytes (script #3) fixes what's *on disk* — it
does not fix what the HTML *references*. Most `<img>`/`srcset`/`poster`/CSS
`url()` tags in this mirror still point at
`/_next/image?url=%2Fimg%2F...&w=384&q=75` instead of the real decoded path
`/img/...`. This script rewrites every such occurrence, in place, across all
HTML files, to the real decoded local path.

Handles:
- `<img src="...">`
- `srcset="..."` (comma-separated, each entry with its own width/density descriptor)
- `poster="..."`
- inline `style="... url(...) ..."`
- `<style>` blocks containing `url(...)`

Explicitly does **not** touch anything that isn't a `/_next/image?url=`
pattern — plain already-correct paths and external/live-domain links are
left byte-for-byte untouched (validated in testing).

```bash
# Dry run first
python3 rewrite_next_image_urls.py \
    --site-root /opt/azurio-clone/site/azuris-nextjs.vercel.app \
    --dry-run --verify --report dry_report.md

# Apply for real
python3 rewrite_next_image_urls.py \
    --site-root /opt/azurio-clone/site/azuris-nextjs.vercel.app \
    --verify --report rewrite_report.md
```

`--verify` checks that every path the script actually rewrote to exists on
disk afterward, and reports any that don't (meaning: still need fetching).
It correctly ignores paths that were never touched by the rewrite (a bug in
an earlier version of the verify logic — checking *all* `/img/` refs in the
file instead of only the ones actually rewritten — was found and fixed).

**Status: already run successfully.** 26 files changed, 3822 occurrences
rewritten, all 271 target paths verified present on disk.

### 5. `fetch_remaining_assets.py` — final asset cleanup

After the image proxy-URL rewrite, `static_audit.py` still showed 126
broken asset refs. Investigation showed these fell into four distinct,
smaller categories (see "Findings log" below for how each was diagnosed).
This script fetches all of them in one pass, with per-category byte-sniffing
so nothing invalid gets saved:

| Category | What | Sniff check |
|---|---|---|
| `favicon` | `/favicon.ico` | ICO or PNG magic bytes |
| `js_chunk` | `/_next/static/chunks/03~yq9q893hmn.js` | Valid UTF-8 text (JS) — **also flagged for manual review**, see below |
| `video` | 18 `.webm`/`.mp4`/`.ogv` files under `/video/` | mp4 `ftyp` box, webm EBML header, or Ogg `OggS` magic |
| `tech_icon` | 8 SVGs under `/img/tech/` | `<svg` or `<?xml` in content |

Every category rejects a soft-404 HTML page disguised as the real asset,
same discipline as script #3.

```bash
pip install requests --break-system-packages

python3 fetch_remaining_assets.py \
    --site-root /opt/azurio-clone/site/azuris-nextjs.vercel.app \
    --live-domain https://azuris-nextjs.vercel.app \
    --report fetch_remaining_report.md \
    --dry-run   # then re-run without this flag to apply
```

**Status: already run.** 27/28 fetched successfully. 1 genuine HTTP 404
(`video/1920x660_cta.ogv` — confirmed gone from the live site too, not a
mirror defect; Ogg Theora is a legacy fallback format most modern sites have
dropped, so this is likely safe to ignore).

⚠️ **Outstanding manual step:** `_next/static/chunks/03~yq9q893hmn.js` was
fetched successfully, but its hash does not match any chunk hash already
present in the local `_next/static/chunks/` directory. This strongly
suggests the HTML pages and this specific chunk were crawled from **two
different deploys** of the live site. It resolves the broken-reference
count, but the code inside it may not perfectly match what the rest of the
crawled JS on this mirror expects. **Before trusting this file in
production:** diff it against the live site's current chunk list, or watch
browser console output on pages that load it for runtime errors.

---

## Current status (as of last audit run)

```
Broken asset refs:        1     (was 3940)
Live-domain asset refs:   0
Broken srcset entries:    0     (was 2542)
Broken internal links:    0
Live-domain links:        0
CSS url() issues:         44    (unchanged — not yet addressed, see below)
Absolute-root-path refs:  4573  (informational only — see note below)
```

The single remaining "broken asset ref" is the missing `.ogv` video
fallback, confirmed genuinely absent from the live site (not a mirror bug).

### Note on absolute-root-path refs

This count is informational, not an error. It means: paths like
`/_next/...` and `/img/...` will resolve correctly **only if the site is
served from domain root** (e.g. `http://localhost:8080/`). If you ever need
to serve this mirror from a subpath (e.g. `https://example.com/azurio-demo/`),
every one of these ~4500 references will break and need a base-path rewrite.
Not urgent unless subpath hosting is planned.

---

## Findings log — how each defect category was diagnosed

Useful context if similar issues crop up elsewhere in the mirror, or if you
need to explain *why* something is broken rather than just that it is.

1. **`_next/image` proxy URLs not resolving to real paths.** Confirmed by
   checking that a fetched image existed on disk at its real path, while
   `grep`-ing HTML files showed they still referenced the old
   `/_next/image?url=...` form, and separately confirming zero HTML files
   referenced the real path directly for that same image. This proved the
   fetch step alone couldn't fix references — a dedicated rewrite was
   required.

2. **Favicon.** `ls favicon.ico` in the site root returned "No such file or
   directory" — genuinely never fetched by the original crawl (not a
   filename mismatch).

3. **JS chunk hash mismatch.** `find` for the referenced hash
   (`03~yq9q893hmn`) turned up nothing, but a *different*-hashed chunk
   (`03j5dzac92d1q.js`) existed in the same directory — indicating a
   build-hash mismatch between the crawled HTML and the crawled JS chunks
   (i.e., different deploys), not a simple missing file.

4. **Videos.** Checked each of the 18 referenced-but-missing video paths
   individually; all 18 were confirmed absent. Cross-referencing against
   what *did* exist in `/video/` showed `.webp` poster images and some
   `.mp4`s were present, but essentially all `.webm`/`.ogv` alternate
   `<source>` candidates were missing — consistent with Puppeteer only
   capturing the network request for whichever `<source>` format Chrome
   actually picked, and never triggering requests for the sibling fallback
   formats.

5. **Tech icons.** `ls img/tech/` returned "No such file or directory" — the
   entire directory was never created during the crawl.

---

## Scope decisions made during this audit

- **Runtime/interactive-element checks cover key page templates only**
  (home, a blog post, a product/project page, etc.), not a full crawl of all
  578 pages. This was a deliberate scope choice to keep the runtime audit
  fast and focused, on the assumption that shared templates/components
  repeat the same JS behavior across pages. If a bug is suspected on a page
  outside the audited set, run `runtime_audit.py` against it directly.
- All repair scripts follow one hard rule: **never write a file to disk
  unless its bytes genuinely sniff as the expected type.** This was a
  deliberate reaction to the specific failure mode that damaged the
  original crawl (soft-404 HTML pages saved with image extensions). Any
  new fetch/repair script added to this repo should follow the same
  discipline — validate content, not just HTTP status code.

---

## Outstanding work (not yet done)

In priority order as of the last working session:

1. **CSS `url()` issues (44)** — all currently isolated to
   `_next/static/chunks/*.css` files (not general page HTML). Two
   sub-categories:
   - Web font files (`.woff`, `.woff2`, `.ttf`, `.svg`) referenced via
     relative `../media/<hash>.<ext>` paths — likely an icon font
     (Phosphor icon set observed) plus the site's main text webfont.
   - A batch of `.webp` images referenced the same way from a different
     CSS chunk (`135.wsn_sc2de.css`) — unclear yet whether these duplicate
     images already present elsewhere in `/img/` or are genuinely unique
     assets never crawled.
   Not yet diagnosed with the same rigor as the HTML-level asset issues —
   next step is confirming whether these are real 404s against the live
   domain or a relative-path resolution problem (the `../media/` path is
   relative to the CSS file's own location, so verify it's being resolved
   from the right base directory before assuming anything is actually
   missing).

2. **JS chunk manual review** — confirm whether
   `_next/static/chunks/03~yq9q893hmn.js` is safe to use despite the
   hash mismatch (see "Outstanding manual step" above).

3. **Runtime bugs identified in the original headless-browser pass:**
   - A broken slider (JS-dependent UI element not functioning against the
     local asset set — needs re-verification now that assets are fixed, in
     case it was actually an asset-loading failure rather than a logic
     bug).
   - A dead cursor effect (silently failing — no console error, but the
     effect doesn't work).
   Re-run `runtime_audit.py` against the affected templates now that the
   asset layer is mostly clean, since some "broken" interactive elements
   may turn out to have been secondary symptoms of missing images/video
   rather than independent JS bugs.

4. **Visual/manual browser QA** — a pass of actually loading the site
   locally (`python3 -m http.server` from the site root) and eyeballing
   key pages: favicon in the tab, tech icons rendering, hero/background
   videos playing, console free of red errors, and manually exercising the
   slider and cursor effect.

---

## How to work on this repo (for any AI agent)

1. **Always start with `static_audit.py`** to get current, ground-truth
   numbers — don't trust numbers from a previous session without
   re-running it, since fixes may have landed since.
2. **Read `report_static.md`** (or `report_static.json` for programmatic
   access) before writing any new repair script — it tells you exactly
   which files/tags/attrs/URLs are affected, so you can target a fix
   precisely instead of guessing.
3. **Never write asset bytes to disk without sniffing them first.** Follow
   the pattern in `fetch_missing_images.py` / `fetch_remaining_assets.py`
   — check magic bytes / content signature per asset type, reject anything
   that looks like an HTML error page, and always support `--dry-run`.
4. **Test repair scripts against a synthetic fixture before running them
   against the real 578-file mirror.** Every script in this repo was
   validated this way — build a small fake directory mimicking the real
   defect, run the script, confirm exact expected behavior (including that
   it does NOT touch things it shouldn't), only then run for real.
5. **Re-run `static_audit.py` after every repair step** to confirm the fix
   landed and to check for regressions, before moving to the next issue.
6. **When something looks broken, diagnose before fixing.** Several issues
   in this repo turned out to be different root causes that looked similar
   on the surface (e.g. "missing favicon" was a true miss, but "missing JS
   chunk" was actually a build-hash mismatch with a same-named-different-hash
   file sitting right next to it). Use `ls`, `find`, and `grep` to confirm
   the actual on-disk state before writing a fetch/rewrite script.

---

## Quick reference — full command sequence from a clean checkout

```bash
cd /opt/azurio-clone

# 1. Baseline audit
python3 static_audit.py site/azuris-nextjs.vercel.app \
    --live-domain azuris-nextjs.vercel.app --report report_static.md

# 2. Fetch missing proxy-referenced images
pip install requests --break-system-packages
python3 fetch_missing_images.py \
    --site-root site/azuris-nextjs.vercel.app \
    --live-domain https://azuris-nextjs.vercel.app \
    --static-report report_static.md --report fetch_report.md

# 3. Rewrite proxy URLs to real decoded paths
python3 rewrite_next_image_urls.py \
    --site-root site/azuris-nextjs.vercel.app \
    --verify --report rewrite_report.md

# 4. Re-audit to find what's still missing
python3 static_audit.py site/azuris-nextjs.vercel.app \
    --live-domain azuris-nextjs.vercel.app --report report_static.md

# 5. Fetch remaining categorized assets (favicon, JS chunk, video, tech icons)
python3 fetch_remaining_assets.py \
    --site-root site/azuris-nextjs.vercel.app \
    --live-domain https://azuris-nextjs.vercel.app \
    --report fetch_remaining_report.md

# 6. Final audit
python3 static_audit.py site/azuris-nextjs.vercel.app \
    --live-domain azuris-nextjs.vercel.app --report report_static.md

# 7. Serve locally for manual/visual QA
cd site/azuris-nextjs.vercel.app && python3 -m http.server 8080
# open http://localhost:8080/

# 8. Runtime/interactive-element audit (requires Playwright)
pip install playwright --break-system-packages && playwright install chromium
python3 runtime_audit.py   # see script --help for template-scoping flags
```
