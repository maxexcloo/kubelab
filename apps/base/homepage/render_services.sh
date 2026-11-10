#!/bin/sh
set -eu

# Render only non-secret Homelab endpoint references; Homepage owns widget secrets.
output=${1:?Usage: render_services.sh output homelab-directory}
homelab_directory=${2:?Usage: render_services.sh output homelab-directory}
: "${HOMELAB_INFRASTRUCTURE_FILE:?HOMELAB_INFRASTRUCTURE_FILE is required}"
: "${HOMEPAGE_BESZEL_ROUTES:?HOMEPAGE_BESZEL_ROUTES is required}"
temporary_directory=$(mktemp -d)
trap 'rm -fr "$temporary_directory"' EXIT

script_directory=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
BESZEL_ROUTES="$HOMEPAGE_BESZEL_ROUTES" INFRASTRUCTURE="$HOMELAB_INFRASTRUCTURE_FILE" \
  PROVIDERS="$homelab_directory/data/providers.yaml" \
  yq --from-file "$script_directory/machine_widgets.yq" \
  "$homelab_directory/data/machines.yaml" > "$temporary_directory/machines.yaml"
# Resolve inventory references in one pass, including nested widget URLs.
MACHINES="$homelab_directory/data/machines.yaml" DOMAINS="$homelab_directory/data/domains.yaml" \
  INFRASTRUCTURE="$HOMELAB_INFRASTRUCTURE_FILE" \
  yq --from-file "$script_directory/resolve_endpoints.yq" \
  "$temporary_directory/machines.yaml" > "$output"
