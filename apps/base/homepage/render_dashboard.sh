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

usage='Usage: render_dashboard.sh source-directory output-directory publish-directory'
source_directory=${1:?$usage}
output_directory=${2:?$usage}
publish_directory=${3:?$usage}
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
yq -p=json -o=yaml '[.items[] |
  select(.metadata.annotations."gethomepage.dev/enabled" == "true") |
  {"annotations": (.metadata.annotations |
    with_entries(select(.key | test("^(gethomepage\\.dev|monitoring\\.excloo\\.dev)/")))),
   "hostnames": .spec.hostnames, "labels": (.metadata.labels // {}),
   "name": .metadata.name, "namespace": .metadata.namespace} |
  with(select(.annotations."gethomepage.dev/group" == "Minilab");
    .annotations."gethomepage.dev/group" = "Mini" |
    .homeName = (.annotations."gethomepage.dev/name" | sub("^[^:]*: "; "")))]
' "$temporary_directory/httproutes.json" > "$temporary_directory/routes.yaml"
yq -e 'length > 0' "$temporary_directory/routes.yaml" >/dev/null
sh "$script_directory/route_nodes.sh" "$temporary_directory/routes.yaml" "$temporary_directory/local-routes.yaml"

# Each cluster's Homepage publishes its own routes, with placement, for the
# others; an unreachable cluster drops out until it answers again.
mkdir "$temporary_directory/clusters"
CLUSTER="$HOMEPAGE_CLUSTER" yq -o=json -I=0 '.[].cluster = strenv(CLUSTER)' \
  "$temporary_directory/local-routes.yaml" > "$temporary_directory/clusters/$HOMEPAGE_CLUSTER.json"
for cluster in $(yq '.clusters | keys | .[]' "$homelab_directory/data/clusters.yaml"); do
  [ "$cluster" != "$HOMEPAGE_CLUSTER" ] || continue
  if wget -O "$temporary_directory/remote.json" -q -T 10 \
    "https://homepage.$cluster.excloo.dev/dashboard/routes.json" &&
    yq -e -p=json 'tag == "!!seq" and length > 0' "$temporary_directory/remote.json" >/dev/null; then
    CLUSTER="$cluster" yq -p=json -o=json -I=0 '.[].cluster = strenv(CLUSTER)' \
      "$temporary_directory/remote.json" > "$temporary_directory/clusters/$cluster.json"
  else
    echo "Skipping cluster $cluster: its Homepage routes are unavailable" >&2
  fi
done
yq ea -o=yaml '[.[]]' "$temporary_directory/clusters/"*.json > "$temporary_directory/inventory.yaml"

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
publish() {
  if ! cmp -s "$1" "$2/${1##*/}"; then
    staged_output=$(mktemp "$2/${1##*/}.XXXXXX")
    cp "$1" "$staged_output"
    chmod 644 "$staged_output"
    mv "$staged_output" "$2/${1##*/}"
  fi
}
mkdir -p "$output_directory" "$publish_directory"
# Homepage serves only public files present when it starts, so publish routes
# before settings.
yq -o=json '.' "$temporary_directory/local-routes.yaml" > "$temporary_directory/routes.json"
publish "$temporary_directory/routes.json" "$publish_directory"
for file in custom.css custom.js docker.yaml kubernetes.yaml widgets.yaml bookmarks.yaml services.yaml settings.yaml; do
  publish "$temporary_directory/config/$file" "$output_directory"
done
