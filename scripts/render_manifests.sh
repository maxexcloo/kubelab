#!/usr/bin/env bash
set -euo pipefail

# Flylab's Gatus renderer reads the per-cluster app and platform outputs.
manifest_directory="${1:?Usage: render_manifests.sh <directory>}"

mkdir -p "${manifest_directory}/clusters"
for cluster_directory in clusters/*/; do
  cluster="$(basename "${cluster_directory}")"
  kubectl kustomize "clusters/${cluster}" >"${manifest_directory}/clusters/${cluster}.yaml"
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
      kubectl kustomize "${target}" >"${manifest_file}"
    fi
  done
