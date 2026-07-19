#!/usr/bin/env bash
set -euo pipefail
SITE_ROOT="/opt/azurio-clone/site/azuris-nextjs.vercel.app"

echo "=== Total files under _next/image/ ==="
find "${SITE_ROOT}/_next/image" -type f | wc -l

echo ""
echo "=== File sizes (first 10) — real images would be KB-MB, error pages are usually tiny/uniform ==="
find "${SITE_ROOT}/_next/image" -type f -exec ls -la {} \; | head -10

echo ""
echo "=== Content of one such file, first 500 chars (confirms whether it's HTML/error or binary image data) ==="
first_file=$(find "${SITE_ROOT}/_next/image" -type f | head -1)
echo "Inspecting: $first_file"
head -c 500 "$first_file"
echo ""
echo ""
echo "=== file(1) type detection on 5 samples ==="
find "${SITE_ROOT}/_next/image" -type f | head -5 | xargs -I{} file "{}"

echo ""
echo "=== Are all these .html files roughly the same size? (suggests identical error/404 page) ==="
find "${SITE_ROOT}/_next/image" -type f -exec stat -c "%s" {} \; | sort -n | uniq -c | sort -rn | head -10
