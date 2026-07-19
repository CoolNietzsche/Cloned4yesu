#!/usr/bin/env bash
set -euo pipefail
SITE_ROOT="/opt/azurio-clone/site/azuris-nextjs.vercel.app"

echo "=== Full listing of everything actually present under /img ==="
find "${SITE_ROOT}/img" -type f -exec ls -la {} \;

echo ""
echo "=== Full directory tree under /img ==="
find "${SITE_ROOT}/img" -type d

echo ""
echo "=== Total size of /img directory ==="
du -sh "${SITE_ROOT}/img" 2>/dev/null || echo "du failed"

echo ""
echo "=== Are there any images ANYWHERE else in the mirror (not just /img)? ==="
find "${SITE_ROOT}" -type f \( -iname "*.webp" -o -iname "*.jpg" -o -iname "*.jpeg" -o -iname "*.png" -o -iname "*.avif" \) | wc -l
echo "--- first 40 of those, wherever they are ---"
find "${SITE_ROOT}" -type f \( -iname "*.webp" -o -iname "*.jpg" -o -iname "*.jpeg" -o -iname "*.png" -o -iname "*.avif" \) | head -40

echo ""
echo "=== Check the _next/image directory itself (sometimes crawlers dump optimizer output here) ==="
find "${SITE_ROOT}" -path "*_next/image*" -type f 2>/dev/null | head -20
find "${SITE_ROOT}" -path "*_next/image*" -type d 2>/dev/null

echo ""
echo "=== Total file count in the entire site root, for scale ==="
find "${SITE_ROOT}" -type f | wc -l
