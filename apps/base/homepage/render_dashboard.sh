#!/bin/sh
set -eu

if [ "${1:-}" = --watch ]; then
  shift
  trap 'exit 0' INT TERM
  while true; do
    if ! sh "$0" "$@"; then
      echo 'Homepage refresh failed; retaining the last valid configuration' >&2
    fi
    sleep 300 &
    wait $!
  done
fi

source_directory=${1:?Usage: render_dashboard.sh source-directory output-directory}
output_directory=${2:?Usage: render_dashboard.sh source-directory output-directory}
script_directory=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
temporary_directory=$(mktemp -d)
trap 'rm -rf "$temporary_directory"' EXIT
kubelab_directory=${KUBELAB_DIRECTORY:-}
export HOMEPAGE_CLUSTER="${HOMEPAGE_CLUSTER:-mbk}"

if [ -z "$kubelab_directory" ]; then
  wget -q -T 30 -O "$temporary_directory/kubelab.tar.gz" \
    https://codeload.github.com/maxexcloo/kubelab/tar.gz/refs/heads/main
  kubelab_directory="$temporary_directory/kubelab"
  mkdir "$kubelab_directory"
  tar -xzf "$temporary_directory/kubelab.tar.gz" -C "$kubelab_directory" --strip-components=1
fi

# Use the same rendered route annotations as external monitoring. Never execute
# scripts from the downloaded checkout or connect to another cluster's API.
: > "$temporary_directory/routes.json"
for overlay in "$kubelab_directory"/apps/overlays/*; do
  [ -d "$overlay" ] || continue
  cluster=${overlay##*/}
  for target in "$overlay" "$kubelab_directory/clusters/$cluster/platform"; do
    "${KUBECTL:-kubectl}" kustomize "$target" > "$temporary_directory/manifests.yaml"
    CLUSTER="$cluster" yq -N -o=json -I=0 --from-file "$script_directory/service_routes.yq" \
      "$temporary_directory/manifests.yaml" >> "$temporary_directory/routes.json"
  done
done
yq ea -p=json -o=yaml '[.] | map(select(.annotations."gethomepage.dev/enabled" == "true"))' \
  "$temporary_directory/routes.json" > "$temporary_directory/inventory.yaml"
yq -e 'length > 0' "$temporary_directory/inventory.yaml" >/dev/null

mkdir "$temporary_directory/config"
HOMEPAGE_BESZEL_URL=$(yq -r 'map(select(.namespace == "beszel")) | .[0].annotations."gethomepage.dev/href" // ""' "$temporary_directory/inventory.yaml") \
  sh "$script_directory/render_services.sh" "$source_directory/services.yaml" \
  "$temporary_directory/config/services.yaml" "${HOMELAB_DIRECTORY:-}"
cp "$temporary_directory/config/services.yaml" "$temporary_directory/external-services.yaml"
SERVICES="$temporary_directory/config/services.yaml" \
  yq --from-file "$script_directory/dashboard.yq" "$temporary_directory/inventory.yaml" \
  > "$temporary_directory/config/services.yaml.next"
mv "$temporary_directory/config/services.yaml.next" "$temporary_directory/config/services.yaml"

for file in custom.css docker.yaml kubernetes.yaml widgets.yaml; do
  cp "$source_directory/$file" "$temporary_directory/config/$file"
done

# Native Homepage layout preferences override defaults for discovered groups.
# shellcheck disable=SC2016
EXTERNAL_SERVICES="$temporary_directory/external-services.yaml" \
  INVENTORY="$temporary_directory/inventory.yaml" \
  SERVICES="$temporary_directory/config/services.yaml" \
  yq '
    .layout as $preferences |
    (load(strenv(EXTERNAL_SERVICES)) | map(keys | .[])) as $external_groups |
    ((load(strenv(INVENTORY)) | map(.annotations."gethomepage.dev/group")) +
      (load(strenv(SERVICES)) | map(keys | .[])) + ["Providers"] | unique | sort) as $groups |
    .layout = ($groups[] as $group ireduce ({};
      .[$group] = ({"columns": 2, "style": "row", "tab": (["Services"] + ($external_groups | map(select(. == $group) | "Servers")) | .[-1])} * ($preferences[$group] // {}))))
  ' "$source_directory/settings.yaml" > "$temporary_directory/config/settings.yaml"

# Validate the entire refresh before publishing any files. Settings is last so
# its presence also gates the first Homepage startup.
for file in "$temporary_directory/config/"*.yaml; do
  yq '.' "$file" >/dev/null
done
mkdir -p "$output_directory"
for file in custom.css docker.yaml kubernetes.yaml widgets.yaml bookmarks.yaml services.yaml settings.yaml; do
  if ! cmp -s "$temporary_directory/config/$file" "$output_directory/$file"; then
    staged_output=$(mktemp "$output_directory/$file.XXXXXX")
    cp "$temporary_directory/config/$file" "$staged_output"
    chmod 644 "$staged_output"
    mv "$staged_output" "$output_directory/$file"
  fi
done
