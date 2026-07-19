#!/usr/bin/env bash
set -euo pipefail
SITE_ROOT="/opt/azurio-clone/site/azuris-nextjs.vercel.app"

echo "=== Confirm the real image now exists on disk ==="
ls -la "${SITE_ROOT}/img/avatars/300x300_ava-01.webp" 2>&1

echo ""
echo "=== Confirm the HTML still references the OLD proxy URL, not the new real path ==="
grep -o '/_next/image?url=%2Fimg%2Favatars%2F300x300_ava-01[^"'"'"']*' "${SITE_ROOT}"/*/index.html 2>/dev/null | head -3

echo ""
echo "=== Does ANY html file already reference the real path directly? ==="
grep -rl "/img/avatars/300x300_ava-01.webp" "${SITE_ROOT}" --include="*.html" | head -3 || echo "(no matches - confirms HTML never points at the real path)"
