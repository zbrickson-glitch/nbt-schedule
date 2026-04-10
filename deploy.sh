#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORKSPACE_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

deploy_legacy() {
  echo "Running DB schema migration..."
  kubectl exec -n zachdb deploy/zachdb-postgres -- psql -U zachdb -d zachdb \
    -c "$(cat "$SCRIPT_DIR/sql/001_schema.sql")"

  echo "Applying k3s manifests..."
  kubectl apply -f "$WORKSPACE_ROOT/infra/manifests/nbt/deployment.yaml"

  echo "Waiting for rollout..."
  kubectl -n nbt rollout status deploy/nbt-schedule-service --timeout=120s

  echo "Health check..."
  curl -sf http://schedule.k3s.local/api/health || echo "Warning: health check failed - check ingress"

  echo "Legacy deploy complete!"
}

deploy_cloudflare_dry() {
  echo "Running Cloudflare dry run..."
  cd "$SCRIPT_DIR/cloudflare"
  node node_modules/wrangler/bin/wrangler.js deploy --dry-run
}

deploy_cloudflare() {
  echo "Deploying Cloudflare public site..."
  cd "$SCRIPT_DIR/cloudflare"
  node node_modules/wrangler/bin/wrangler.js deploy
}

case "${1:-cloudflare-dry}" in
  legacy)
    deploy_legacy
    ;;
  cloudflare-dry)
    deploy_cloudflare_dry
    ;;
  cloudflare)
    deploy_cloudflare
    ;;
  *)
    echo "Usage: $0 [cloudflare-dry|cloudflare|legacy]"
    echo ""
    echo "Commands:"
    echo "  cloudflare-dry  Validate the Worker/assets bundle without deploying"
    echo "  cloudflare      Deploy the public Cloudflare Worker + assets"
    echo "  legacy          Run the existing k3s deployment flow"
    exit 1
    ;;
esac
