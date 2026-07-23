#!/usr/bin/env bash
# Deploy the StartupET static site (StartupetLanding/) to the cPanel subdomain.
# Usage:  ./deploy.sh
set -euo pipefail

# ---- edit these four once ----
CPANEL_HOST="YOUR_CPANEL_HOST"        # e.g. server123.web-hosting.com  (cPanel → SSH Access)
CPANEL_USER="paperlao"
SSH_PORT="22"                         # your cPanel SSH port
DOCROOT="/home/paperlao/nslp.landing.paperless.et"
# ------------------------------

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC="$REPO_DIR/StartupetLanding/"     # trailing slash = copy CONTENTS into docroot

echo "→ Pulling latest StartupetLanding…"
git -C "$REPO_DIR" checkout StartupetLanding
git -C "$REPO_DIR" pull --ff-only origin StartupetLanding

echo "→ Syncing to ${CPANEL_USER}@${CPANEL_HOST}:${DOCROOT} …"
rsync -avz --delete \
  -e "ssh -p ${SSH_PORT}" \
  --exclude 'cgi-bin' --exclude '.well-known' --exclude '.htaccess' \
  "$SRC" "${CPANEL_USER}@${CPANEL_HOST}:${DOCROOT}/"

echo "✅ Deployed. Open https://nslp.landing.paperless.et and hard-refresh (Ctrl/Cmd+Shift+R)."
