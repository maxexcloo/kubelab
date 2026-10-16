#!/bin/sh
set -eu
: "${HOMEPAGE_CLUSTER:?HOMEPAGE_CLUSTER is required}"
export HOMEPAGE_CLUSTER

if [ "${1:-}" = --watch ]; then
  shift
  trap 'exit 0' INT TERM
  while true; do
    if ! sh "$0" "$@"; then
      echo 'Homepage refresh failed; retaining the last valid configuration' >&2
    elif [ -n "${HOMEPAGE_REVALIDATE_URL:-}" ]; then
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
route_script=${HOMEPAGE_ROUTE_SCRIPT:-$script_directory/../../../scripts/service-routes/service_routes.yq}
temporary_directory=$(mktemp -d)
trap 'rm -fr "$temporary_directory"' EXIT
kubelab_directory=${KUBELAB_DIRECTORY:-}

if [ -z "$kubelab_directory" ]; then
  # Follow the local cluster's applied configuration rather than newer Git commits.
  revision=$("${KUBECTL:-kubectl}" --namespace flux-system get kustomization apps \
    --output jsonpath='{.status.lastAppliedRevision}')
  revision=${revision##*@sha1:}
  case "$revision" in
    *[!a-f0-9]* | '') echo 'Missing or invalid applied Flux revision' >&2; exit 1 ;;
  esac
  [ "${#revision}" -eq 40 ] || { echo 'Invalid applied Flux revision length' >&2; exit 1; }
  cache_directory=${HOMEPAGE_CACHE_DIRECTORY:-/tmp/homepage}
  kubelab_directory="$cache_directory/kubelab"
  if [ ! -d "$kubelab_directory" ] || [ "$(cat "$cache_directory/revision" 2>/dev/null || true)" != "$revision" ]; then
    wget -O "$temporary_directory/kubelab.tar.gz" -q -T 30 \
      "https://codeload.github.com/maxexcloo/kubelab/tar.gz/$revision"
    mkdir "$temporary_directory/kubelab"
    tar -xzf "$temporary_directory/kubelab.tar.gz" -C "$temporary_directory/kubelab" --strip-components=1
    mkdir -p "$cache_directory"
    rm -fr "$kubelab_directory"
    mv "$temporary_directory/kubelab" "$kubelab_directory"
    printf '%s\n' "$revision" > "$cache_directory/revision"
  fi
fi

homelab_directory=${HOMELAB_DIRECTORY:-}
if [ -z "$homelab_directory" ]; then
  wget -O "$temporary_directory/homelab.tar.gz" -q -T 30 \
    https://codeload.github.com/maxexcloo/homelab/tar.gz/refs/heads/main
  homelab_directory="$temporary_directory/homelab"
  mkdir "$homelab_directory"
  tar -xzf "$temporary_directory/homelab.tar.gz" -C "$homelab_directory" --strip-components=1
fi
export HOMELAB_MACHINES="$homelab_directory/data/machines.yaml"

# Use the same rendered route annotations as external monitoring. Never execute
# scripts from the downloaded checkout or connect to another cluster's API.
: > "$temporary_directory/routes.json"
mini_apps_directory=${MINI_APPS_DIRECTORY:-}
for overlay in "$kubelab_directory"/apps/overlays/*; do
  [ -d "$overlay" ] || continue
  cluster=${overlay##*/}
  for target in "$overlay" "$kubelab_directory/clusters/$cluster/platform"; do
    "${KUBECTL:-kubectl}" kustomize "$target" > "$temporary_directory/manifests.yaml"
    CLUSTER="$cluster" yq --from-file "$route_script" -I=0 -N -o=json \
      "$temporary_directory/manifests.yaml" >> "$temporary_directory/routes.json"
    mini_apps_path=$(yq 'select(.kind == "Kustomization" and .metadata.name == "mini-apps") | .spec.path' "$temporary_directory/manifests.yaml")
    [ -n "$mini_apps_path" ] || continue
    if [ -z "$mini_apps_directory" ]; then
      mini_apps_url=$(yq 'select(.kind == "GitRepository" and .metadata.name == "mini-apps") | .spec.url' "$temporary_directory/manifests.yaml")
      mini_apps_repository=${mini_apps_url#https://github.com/}
      mini_apps_repository=${mini_apps_repository%.git}
      case "$mini_apps_repository" in
        '' | *[!a-zA-Z0-9_./-]* | *..*) echo 'Invalid mini-apps repository' >&2; exit 1 ;;
      esac
      mini_apps_revision=$("${KUBECTL:-kubectl}" --namespace flux-system get kustomization mini-apps \
        --output jsonpath='{.status.lastAppliedRevision}' --ignore-not-found)
      mini_apps_revision=${mini_apps_revision##*@sha1:}
      if [ -n "$mini_apps_revision" ]; then
        case "$mini_apps_revision" in
          *[!a-f0-9]*) echo 'Invalid applied mini-apps revision' >&2; exit 1 ;;
        esac
        [ "${#mini_apps_revision}" -eq 40 ] || exit 1
      else
        mini_apps_branch=$(yq 'select(.kind == "GitRepository" and .metadata.name == "mini-apps") | .spec.ref.branch' "$temporary_directory/manifests.yaml")
        mini_apps_revision="refs/heads/$mini_apps_branch"
      fi
      wget -O "$temporary_directory/mini-apps.tar.gz" -q -T 30 \
        "https://codeload.github.com/$mini_apps_repository/tar.gz/$mini_apps_revision"
      mini_apps_directory="$temporary_directory/mini-apps"
      mkdir "$mini_apps_directory"
      tar -xzf "$temporary_directory/mini-apps.tar.gz" -C "$mini_apps_directory" --strip-components=1
    fi
    "${KUBECTL:-kubectl}" kustomize "$mini_apps_directory/$mini_apps_path" > "$temporary_directory/mini-apps.yaml"
    CLUSTER="$cluster" yq --from-file "$route_script" -I=0 -N -o=json \
      "$temporary_directory/mini-apps.yaml" > "$temporary_directory/mini-app-routes.json"
    yq -p=json -o=json -I=0 '.annotations."gethomepage.dev/group" = "Mini Apps"' \
      "$temporary_directory/mini-app-routes.json" >> "$temporary_directory/routes.json"
  done
done
yq ea -p=json -o=yaml '[.] | map(select(.annotations."gethomepage.dev/enabled" == "true"))' \
  "$temporary_directory/routes.json" > "$temporary_directory/inventory.yaml"
yq -e 'length > 0' "$temporary_directory/inventory.yaml" >/dev/null

# Host management stays on Servers; cluster administration tools are services.
yq '
  with(.[] | select(.annotations."gethomepage.dev/group" == "Servers");
    .annotations."gethomepage.dev/group" = "Operations")
' "$temporary_directory/inventory.yaml" > "$temporary_directory/inventory.yaml.next"
mv "$temporary_directory/inventory.yaml.next" "$temporary_directory/inventory.yaml"
sh "$script_directory/route_nodes.sh" "$temporary_directory/inventory.yaml" "$temporary_directory/inventory.yaml.next"
mv "$temporary_directory/inventory.yaml.next" "$temporary_directory/inventory.yaml"

mkdir "$temporary_directory/config"
HOMEPAGE_CLUSTER_NAMES=$(yq -r 'map(.cluster) | unique | join(",")' "$temporary_directory/inventory.yaml") \
HOMEPAGE_BESZEL_URL=$(yq -r 'map(select(.namespace == "beszel")) | .[0].annotations."gethomepage.dev/href" // ""' "$temporary_directory/inventory.yaml") \
  sh "$script_directory/render_services.sh" "$source_directory/services.yaml" \
  "$temporary_directory/config/services.yaml" "$homelab_directory"
SERVICES="$temporary_directory/config/services.yaml" \
  yq --from-file "$script_directory/dashboard.yq" "$temporary_directory/inventory.yaml" \
  > "$temporary_directory/config/services.yaml.next"
mv "$temporary_directory/config/services.yaml.next" "$temporary_directory/config/services.yaml"

# Discover probe keys from Gatus; its native checks own website and DNS health.
gatus_url=$(yq -r 'explode(.) | [.. | select(tag == "!!map" and .widget.type == "gatus") |
  .widget.url] | .[0]' "$temporary_directory/config/services.yaml")
case "$gatus_url" in
  http://* | https://*) ;;
  *) echo 'Missing Gatus widget URL' >&2; exit 1 ;;
esac
gatus_statuses=${HOMEPAGE_GATUS_STATUSES_FILE:-}
gatus_providers_ready() {
  # shellcheck disable=SC2016
  yq -e 'tag == "!!seq" and length > 0' "$gatus_statuses" >/dev/null &&
    PROVIDERS="$homelab_directory/data/providers.yaml" yq -e '
      load(strenv(PROVIDERS)).providers as $providers |
      ([$providers | to_entries[] | select(.value.conditions != null) | .value.name] +
        [$providers | to_entries[] | select(.value.dns != null) |
          (.value.dns.name // (.value.name + " DNS"))]) as $expected |
      [.[] | select(.group == "Providers") | .name] as $available |
      (($expected - $available) | length) == 0
    ' "$gatus_statuses" >/dev/null
}
if [ -z "$gatus_statuses" ]; then
  gatus_statuses="$temporary_directory/gatus.json"
  # Gatus exposes partial endpoint lists while its first checks are still running.
  for _ in $(seq 1 30); do
    if wget -O "$gatus_statuses" -q -T 30 "$gatus_url/api/v1/endpoints/statuses?page=1&pageSize=1" &&
      gatus_providers_ready; then
      break
    fi
    sleep 5
  done
fi
gatus_providers_ready
GATUS_URL="$gatus_url" PROVIDERS="$homelab_directory/data/providers.yaml" \
  yq --from-file "$script_directory/provider_widgets.yq" "$gatus_statuses" > "$temporary_directory/config/providers.yaml"
yq ea '[.[]]' "$temporary_directory/config/services.yaml" "$temporary_directory/config/providers.yaml" \
  > "$temporary_directory/config/services.yaml.next"
mv "$temporary_directory/config/services.yaml.next" "$temporary_directory/config/services.yaml"

for file in custom.css custom.js docker.yaml kubernetes.yaml; do
  cp "$source_directory/$file" "$temporary_directory/config/$file"
done
cluster_label=$(printf '%s' "$HOMEPAGE_CLUSTER" | tr '[:lower:]' '[:upper:]')
printf '\n:root { --homepage-cluster: "%s"; }\n' "$cluster_label" >> "$temporary_directory/config/custom.css"
yq '(.[] | select(has("kubernetes"))).kubernetes.cluster.label = (strenv(HOMEPAGE_CLUSTER) | upcase)' \
  "$source_directory/widgets.yaml" > "$temporary_directory/config/widgets.yaml"

# Nested groups keep identical host and Kubernetes node names on separate tabs.
# shellcheck disable=SC2016
SERVICES="$temporary_directory/config/services.yaml" \
  yq '
    .layout as $preferences |
    load(strenv(SERVICES)) as $services |
    .layout = (["Services", "Clusters", "Servers"][] as $tab ireduce ({};
      ($services | map(select(has($tab))) | .[0][$tab] // []) as $groups |
      with(select(($groups | length) > 0);
        .[$tab] = (($groups[] | keys | .[]) as $group ireduce (
          {"columns": 1, "header": false, "style": "row", "tab": $tab};
            .[$group] = ({"columns": 2, "style": "row"} * ($preferences[$group] // {}) | del(.tab))))))) |
    .layout.Providers = $preferences.Providers
  ' "$source_directory/settings.yaml" > "$temporary_directory/config/settings.yaml"

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
