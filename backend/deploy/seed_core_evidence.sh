#!/bin/sh
set -eu

# Preview (no writes, no embedding call):
#   sh backend/deploy/seed_core_evidence.sh
# Apply to the default production container:
#   sh backend/deploy/seed_core_evidence.sh --apply
# Apply to an explicitly named replacement container before traffic cutover:
#   sh backend/deploy/seed_core_evidence.sh xjie-api-candidate --apply

container="xjie-api"
if [ "$#" -gt 0 ] && [ "${1#--}" = "$1" ]; then
  container="$1"
  shift
fi

docker exec "$container" python -m app.services.literature.core_evidence "$@"
