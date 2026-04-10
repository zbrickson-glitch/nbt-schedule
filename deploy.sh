#!/usr/bin/env bash
# deploy.sh — Deploy nbt-schedule to Cloudflare Workers
# Usage: bash deploy.sh [dev|prod|status]
#   dev    — Deploy to nbt-dev.zachbrickson.dev (iteration/preview)
#   prod   — Deploy to schedule.naenaewhipwhip.com (live site)
#   status — Show recent deployments
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

CF_PROJECT_DEV="nbt-schedule-dev"
CF_PROJECT_PROD="nbt-schedule"

get_cf_creds() {
  export CLOUDFLARE_API_KEY
  export CLOUDFLARE_EMAIL="zbrickson@gmail.com"
  CLOUDFLARE_API_KEY="$(op read 'op://Madge/Cloudflare Global API Key/credential')"
}

case "${1:-dev}" in
  dev)
    get_cf_creds
    echo "=== Deploying to DEV (nbt-dev.zachbrickson.dev) ==="
    cd "$SCRIPT_DIR/cloudflare"
    node node_modules/wrangler/bin/wrangler.js deploy --env dev

    echo ""
    echo "=== DEPLOYED TO DEV ==="
    echo "  Preview: https://nbt-dev.zachbrickson.dev"
    ;;

  prod)
    get_cf_creds
    echo "=== Deploying to PROD (schedule.naenaewhipwhip.com) ==="
    cd "$SCRIPT_DIR/cloudflare"
    node node_modules/wrangler/bin/wrangler.js deploy

    echo ""
    echo "=== DEPLOYED TO PROD ==="
    echo "  Live: https://schedule.naenaewhipwhip.com"
    ;;

  status)
    get_cf_creds
    echo "=== Cloudflare Workers Projects ==="
    echo ""
    echo "--- DEV (nbt-dev.zachbrickson.dev) ---"
    cd "$SCRIPT_DIR/cloudflare"
    node node_modules/wrangler/bin/wrangler.js deployments list --env dev 2>&1 | head -10
    echo ""
    echo "--- PROD (schedule.naenaewhipwhip.com) ---"
    node node_modules/wrangler/bin/wrangler.js deployments list 2>&1 | head -10
    ;;

  *)
    echo "Usage: $0 [dev|prod|status]"
    echo ""
    echo "Commands:"
    echo "  dev      Deploy to nbt-dev.zachbrickson.dev (default, no tests)"
    echo "  prod     Deploy to schedule.naenaewhipwhip.com (live site)"
    echo "  status   Show recent deployments for both projects"
    exit 1
    ;;
esac
