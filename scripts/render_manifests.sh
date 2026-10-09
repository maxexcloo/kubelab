#!/usr/bin/env bash
set -euo pipefail

manifest_directory="${1:?Usage: render_manifests.sh <directory> [cluster ...]}"
shift
clusters=("$@")
if ((${#clusters[@]} == 0)); then
  while IFS= read -r cluster_directory; do
    clusters+=("${cluster_directory##*/}")
  done < <(find clusters -maxdepth 1 -mindepth 1 -type d | sort)
fi

for cluster in "${clusters[@]}"; do
  if [[ ! -d "apps/overlays/${cluster}" || ! -d "clusters/${cluster}/platform" ]]; then
    echo "Unknown or incomplete cluster: ${cluster}" >&2
    exit 2
  fi
  mkdir -p "${manifest_directory}/clusters"
  kustomize build "clusters/${cluster}" >"${manifest_directory}/clusters/${cluster}.yaml"
done

yq eval -N -r '
  select(.apiVersion == "kustomize.toolkit.fluxcd.io/v1" and .kind == "Kustomization") |
  .spec.path
' "${manifest_directory}"/clusters/*.yaml | sort -u |
  while IFS= read -r target; do
    target="${target#./}"
    manifest_file="${manifest_directory}/${target}.yaml"
    if [[ ! -f "${manifest_file}" ]]; then
      mkdir -p "$(dirname "${manifest_file}")"
      kustomize build "${target}" >"${manifest_file}"
    fi
  done
