#!/bin/sh
set -eu
: "${HOMEPAGE_CLUSTER:?HOMEPAGE_CLUSTER is required}"
: "${KUBECTL:?KUBECTL is required}"
export HOMEPAGE_CLUSTER
# HOMELAB_DIRECTORY selects a local Homelab checkout for tests; unset or empty,
# HOMELAB_ARCHIVE is downloaded.

if [ "${1:-}" = --watch ]; then
  shift
  : "${HOMEPAGE_REVALIDATE_URL:?HOMEPAGE_REVALIDATE_URL is required}"
  trap 'exit 0' INT TERM
  while true; do
    if ! sh "$0" "$@"; then
      echo 'Homepage refresh failed; retaining the last valid configuration' >&2
    else
      # Native page caching otherwise leaves new browsers on the image's layout.
      for _ in $(seq 1 30); do
        if wget -O /dev/null -q -T 5 --header 'Host: localhost:3000' "$HOMEPAGE_REVALIDATE_URL"; then
          break
        fi
        sleep 1
      done
    fi
    sleep 300 &
    wait $!
  done
fi

source_directory=${1:?Usage: render_dashboard.sh source-directory output-directory}
output_directory=${2:?Usage: render_dashboard.sh source-directory output-directory}
script_directory=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
temporary_directory=$(mktemp -d)
trap 'rm -fr "$temporary_directory"' EXIT

homelab_directory=${HOMELAB_DIRECTORY:-}
if [ -z "$homelab_directory" ]; then
  homelab_directory="$temporary_directory/homelab"
  mkdir "$homelab_directory"
  wget -O - -q -T 30 "${HOMELAB_ARCHIVE:?HOMELAB_ARCHIVE is required}" |
    tar -xz -C "$homelab_directory" --strip-components=1
fi
export HOMELAB_MACHINES="$homelab_directory/data/machines.yaml"

"$KUBECTL" get httproutes --all-namespaces --output json > "$temporary_directory/httproutes.json"
# Minilab prefixes its route names, which the Home group already states.
yq -p=json -o=yaml '[.items[] | .metadata |
  select(.annotations."gethomepage.dev/enabled" == "true") |
  {"annotations": .annotations, "labels": (.labels // {}), "name": .name, "namespace": .namespace} |
  with(select(.annotations."gethomepage.dev/group" == "Minilab");
    .annotations."gethomepage.dev/group" = "Mini" |
    .homeName = (.annotations."gethomepage.dev/name" | sub("^[^:]*: "; "")))]
' "$temporary_directory/httproutes.json" > "$temporary_directory/routes.yaml"
yq -e 'length > 0' "$temporary_directory/routes.yaml" >/dev/null
sh "$script_directory/route_nodes.sh" "$temporary_directory/routes.yaml" "$temporary_directory/inventory.yaml"

mkdir "$temporary_directory/config"
yq -o=json 'map(select(.namespace == "beszel"))' \
  "$temporary_directory/inventory.yaml" > "$temporary_directory/beszel-routes.json"
HOMEPAGE_BESZEL_ROUTES="$temporary_directory/beszel-routes.json" \
  sh "$script_directory/render_services.sh" "$temporary_directory/external-services.yaml" "$homelab_directory"
SERVICES="$temporary_directory/external-services.yaml" \
  yq --from-file "$script_directory/dashboard.yq" "$temporary_directory/inventory.yaml" \
  > "$temporary_directory/dashboard-services.yaml"
yq --from-file "$script_directory/provider_widgets.yq" "$homelab_directory/data/providers.yaml" \
  > "$temporary_directory/providers.yaml"
yq ea '[.[]]' "$temporary_directory/dashboard-services.yaml" "$temporary_directory/providers.yaml" \
  > "$temporary_directory/config/services.yaml"
printf '[]\n' > "$temporary_directory/config/bookmarks.yaml"

for file in custom.css custom.js docker.yaml kubernetes.yaml; do
  cp "$source_directory/$file" "$temporary_directory/config/$file"
done
printf '\n:root { --homepage-cluster: "%s"; }\n' "$HOMEPAGE_CLUSTER" >> "$temporary_directory/config/custom.css"
yq '(.[] | select(has("kubernetes"))).kubernetes.cluster.label = strenv(HOMEPAGE_CLUSTER)' \
  "$source_directory/widgets.yaml" > "$temporary_directory/widgets.yaml"
MACHINES="$homelab_directory/data/machines.yaml" DOMAINS="$homelab_directory/data/domains.yaml" \
  INFRASTRUCTURE="$HOMELAB_INFRASTRUCTURE_FILE" \
  yq --from-file "$script_directory/resolve_endpoints.yq" \
  "$temporary_directory/widgets.yaml" > "$temporary_directory/config/widgets.yaml"

SERVICES="$temporary_directory/config/services.yaml" \
  yq --from-file "$script_directory/layout.yq" "$source_directory/settings.yaml" \
  > "$temporary_directory/config/settings.yaml"

# Validate the entire refresh before publishing any files. Settings is last so
# its presence also gates the first Homepage startup.
for file in "$temporary_directory/config/"*.yaml; do
  yq '.' "$file" >/dev/null
done
mkdir -p "$output_directory"
for file in custom.css custom.js docker.yaml kubernetes.yaml widgets.yaml bookmarks.yaml services.yaml settings.yaml; do
  if ! cmp -s "$temporary_directory/config/$file" "$output_directory/$file"; then
    staged_output=$(mktemp "$output_directory/$file.XXXXXX")
    cp "$temporary_directory/config/$file" "$staged_output"
    chmod 644 "$staged_output"
    mv "$staged_output" "$output_directory/$file"
  fi
done
