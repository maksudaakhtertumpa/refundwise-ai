#!/usr/bin/env bash
# Load RefundWise sample data into the Postgres that ships with the local Zetaris install.
# Usage (from the project folder):  bash scripts/load_data.sh
set -euo pipefail

CONTAINER="${ZETARIS_PG_CONTAINER:-zetaris-postgres-1}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"

if ! docker info >/dev/null 2>&1; then
  echo "Docker is not running. Open Docker Desktop first (open -a Docker), wait for it, then retry."
  exit 1
fi
if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  echo "Container $CONTAINER is not running."
  echo "Start Zetaris first:  cd ~/zetaris/zetaris-platform && docker compose start"
  exit 1
fi

docker exec -i "$CONTAINER" psql -U zetaris -d metastore -v ON_ERROR_STOP=1 -q \
  < "$HERE/data/seed_postgres.sql"

echo
echo "Row counts:"
docker exec "$CONTAINER" psql -U zetaris -d shop_orders  -Atc "select '  shop_orders.orders          ', count(*) from orders"
docker exec "$CONTAINER" psql -U zetaris -d support_desk -Atc "select '  support_desk.customers      ', count(*) from customers"
docker exec "$CONTAINER" psql -U zetaris -d support_desk -Atc "select '  support_desk.refund_history ', count(*) from refund_history"
docker exec "$CONTAINER" psql -U zetaris -d policy_kb    -Atc "select '  policy_kb.refund_policy     ', count(*) from refund_policy"
echo
echo "Done. Next: register the three sources in Zetaris (data/zetaris_register.sql)."
