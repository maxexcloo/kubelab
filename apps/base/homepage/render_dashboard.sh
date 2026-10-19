#!/bin/sh
set -eu
: "${HOMEPAGE_CLUSTER:?HOMEPAGE_CLUSTER is required}"
: "${HOMEPAGE_ROUTE_SCRIPT:?HOMEPAGE_ROUTE_SCRIPT is required}"
: "${KUBECTL:?KUBECTL is required}"
export HOMEPAGE_CLUSTER
# KUBELAB_DIRECTORY, HOMELAB_DIRECTORY, MINILAB_DIRECTORY and
# HOMEPAGE_GATUS_STATUSES_FILE select local inputs for tests. Unset or empty,
# the live repositories are downloaded and Gatus is queried.

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
# Keep downloads and Kustomize rendering separate from dashboard assembly.
github_repository() (
  repository=${1#https://github.com/}
  repository=${repository%.git}
  case "$repository" in
    '' | *[!a-zA-Z0-9_./-]* | *..*) echo "Invalid GitHub repository: $1" >&2; exit 1 ;;
  esac
  printf '%s' "$repository"
)
download_repository() (
  repository=$1
  revision=$2
  destination=$3
  wget -O "$temporary_directory/repository.tar.gz" -q -T 30 \
    "https://codeload.github.com/$repository/tar.gz/$revision"
  mkdir "$destination"
  tar -xzf "$temporary_directory/repository.tar.gz" -C "$destination" --strip-components=1
)
applied_revision() (
  revision=$("$KUBECTL" --namespace flux-system get kustomization "$1" \
    --output jsonpath='{.status.lastAppliedRevision}' --ignore-not-found)
  revision=${revision##*@sha1:}
  if [ -n "$revision" ]; then
    case "$revision" in
      *[!a-f0-9]*) echo 'Invalid applied Flux revision' >&2; exit 1 ;;
    esac
    [ "${#revision}" -eq 40 ] || { echo 'Invalid applied Flux revision length' >&2; exit 1; }
  fi
  printf '%s' "$revision"
)
render_routes() {
  "$KUBECTL" kustomize "$1" > "$temporary_directory/manifests.yaml"
  CLUSTER="$cluster" yq --from-file "$HOMEPAGE_ROUTE_SCRIPT" -I=0 -N -o=json \
    "$temporary_directory/manifests.yaml"
}

kubelab_directory=${KUBELAB_DIRECTORY:-}

if [ -z "$kubelab_directory" ]; then
  # Follow the local cluster's applied configuration rather than newer Git commits.
  revision=$(applied_revision apps)
  : "${revision:?Missing applied Flux revision}"
  cache_directory=${HOMEPAGE_CACHE_DIRECTORY:?HOMEPAGE_CACHE_DIRECTORY is required}
  kubelab_directory="$cache_directory/kubelab"
  if [ ! -d "$kubelab_directory" ] || [ "$(cat "$cache_directory/revision" 2>/dev/null || true)" != "$revision" ]; then
    # The applied revision belongs to the cluster's own Flux source.
    kubelab_url=$("$KUBECTL" --namespace flux-system get gitrepository flux-system --output jsonpath='{.spec.url}')
    kubelab_repository=$(github_repository "$kubelab_url")
    download_repository "$kubelab_repository" "$revision" "$temporary_directory/kubelab"
    mkdir -p "$cache_directory"
    rm -fr "$kubelab_directory"
    mv "$temporary_directory/kubelab" "$kubelab_directory"
    printf '%s\n' "$revision" > "$cache_directory/revision"
  fi
fi

homelab_directory=${HOMELAB_DIRECTORY:-}
if [ -z "$homelab_directory" ]; then
  homelab_repository=$(github_repository "${HOMELAB_REPOSITORY:?HOMELAB_REPOSITORY is required}")
  homelab_directory="$temporary_directory/homelab"
  download_repository "$homelab_repository" "refs/heads/${HOMELAB_BRANCH:?HOMELAB_BRANCH is required}" "$homelab_directory"
fi
export HOMELAB_MACHINES="$homelab_directory/data/machines.yaml"

# Use the same rendered route annotations as external monitoring. Never execute
# scripts from the downloaded checkout or connect to another cluster's API.
: > "$temporary_directory/routes.json"
minilab_directory=${MINILAB_DIRECTORY:-}
for overlay in "$kubelab_directory"/apps/overlays/*; do
  [ -d "$overlay" ] || continue
  cluster=${overlay##*/}
  for target in "$overlay" "$kubelab_directory/clusters/$cluster/platform"; do
    render_routes "$target" >> "$temporary_directory/routes.json"
    mini_apps_path=$(yq 'select(.kind == "Kustomization" and .metadata.name == "mini-apps") | .spec.path' "$temporary_directory/manifests.yaml")
    [ -n "$mini_apps_path" ] || continue
    if [ -z "$minilab_directory" ]; then
      minilab_url=$(yq -e 'select(.kind == "GitRepository" and .metadata.name == "mini-apps") | .spec.url' "$temporary_directory/manifests.yaml")
      minilab_repository=$(github_repository "$minilab_url")
      minilab_revision=$(applied_revision mini-apps)
      if [ -z "$minilab_revision" ]; then
        minilab_branch=$(yq -e 'select(.kind == "GitRepository" and .metadata.name == "mini-apps") | .spec.ref.branch' "$temporary_directory/manifests.yaml")
        minilab_revision="refs/heads/$minilab_branch"
      fi
      minilab_directory="$temporary_directory/minilab"
      download_repository "$minilab_repository" "$minilab_revision" "$minilab_directory"
    fi
    render_routes "$minilab_directory/$mini_apps_path" > "$temporary_directory/mini-app-routes.json"
    yq -p=json -o=json -I=0 '.annotations."gethomepage.dev/group" = "Mini Apps"' \
      "$temporary_directory/mini-app-routes.json" >> "$temporary_directory/routes.json"
  done
done
# Host management stays on Servers; cluster administration tools are services.
yq ea -p=json -o=yaml '
  [.] | map(select(.annotations."gethomepage.dev/enabled" == "true")) |
  with(.[] | select(.annotations."gethomepage.dev/group" == "Servers");
    .annotations."gethomepage.dev/group" = "Operations")
' "$temporary_directory/routes.json" > "$temporary_directory/routes.yaml"
yq -e 'length > 0' "$temporary_directory/routes.yaml" >/dev/null
sh "$script_directory/route_nodes.sh" "$temporary_directory/routes.yaml" "$temporary_directory/inventory.yaml"

mkdir "$temporary_directory/config"
HOMEPAGE_CLUSTER_NAMES=$(yq -r 'map(.cluster) | unique | join(",")' "$temporary_directory/inventory.yaml") \
  sh "$script_directory/render_services.sh" "$source_directory/services.yaml" \
  "$temporary_directory/external-services.yaml" "$homelab_directory"
SERVICES="$temporary_directory/external-services.yaml" \
  yq --from-file "$script_directory/dashboard.yq" "$temporary_directory/inventory.yaml" \
  > "$temporary_directory/dashboard-services.yaml"

# Discover probe keys from Gatus; its native checks own website and DNS health.
gatus_url=$(yq -r 'explode(.) | [.. | select(tag == "!!map" and .widget.type == "gatus") |
  .widget.url] | .[0]' "$temporary_directory/dashboard-services.yaml")
case "$gatus_url" in
  http://* | https://*) ;;
  *) echo 'Missing Gatus widget URL' >&2; exit 1 ;;
esac
gatus_statuses=${HOMEPAGE_GATUS_STATUSES_FILE:-}
render_providers() {
  GATUS_URL="$gatus_url" PROVIDERS="$homelab_directory/data/providers.yaml" \
    yq -e --from-file "$script_directory/provider_widgets.yq" "$gatus_statuses" \
    > "$temporary_directory/providers.yaml"
}
if [ -n "$gatus_statuses" ]; then
  render_providers
else
  gatus_statuses="$temporary_directory/gatus.json"
  # Gatus exposes partial endpoint lists while its first checks are still running.
  for attempt in $(seq 1 30); do
    if wget -O "$gatus_statuses" -q -T 30 "$gatus_url/api/v1/endpoints/statuses?page=1&pageSize=1" &&
      render_providers; then
      break
    fi
    [ "$attempt" -lt 30 ] || exit 1
    sleep 5
  done
fi
yq ea '[.[]]' "$temporary_directory/dashboard-services.yaml" "$temporary_directory/providers.yaml" \
  > "$temporary_directory/config/services.yaml"
cp "$temporary_directory/bookmarks.yaml" "$temporary_directory/config/bookmarks.yaml"

for file in custom.css custom.js docker.yaml kubernetes.yaml; do
  cp "$source_directory/$file" "$temporary_directory/config/$file"
done
printf '\n:root { --homepage-cluster: "%s"; }\n' "$HOMEPAGE_CLUSTER" >> "$temporary_directory/config/custom.css"
yq '(.[] | select(has("kubernetes"))).kubernetes.cluster.label = strenv(HOMEPAGE_CLUSTER)' \
  "$source_directory/widgets.yaml" > "$temporary_directory/config/widgets.yaml"

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
