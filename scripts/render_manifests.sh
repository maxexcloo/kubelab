#!/usr/bin/env bash
set -euo pipefail

# Flylab's Gatus renderer reads the per-cluster app and platform outputs.
mkdir -p "${1:?Usage: render_manifests.sh <directory>}/clusters"
manifest_directory="$(cd "$1" && pwd)"
build_directory="$(mktemp -d "${TMPDIR:-/tmp}/kubelab-render.XXXXXX")"
trap 'rm -fr -- "${build_directory:?}"' EXIT

# Flux rewrites a kustomization.yaml while it builds it, so build a copy.
cp -R apps clusters platform "${build_directory}/"
cd "${build_directory}"
kustomization_file="${build_directory}/flux-kustomization.yaml"

for cluster_directory in clusters/*/; do
  cluster="$(basename "${cluster_directory}")"
  cluster_file="${manifest_directory}/clusters/${cluster}.yaml"
  kubectl kustomize "clusters/${cluster}" >"${cluster_file}"
  # Build each Flux Kustomization as Flux does, with its strict substitutions.
  yq eval -N -r '
    select(.apiVersion == "kustomize.toolkit.fluxcd.io/v1" and .kind == "Kustomization") |
    .metadata.name
  ' "${cluster_file}" |
    while IFS= read -r name; do
      KUSTOMIZATION="${name}" yq eval '
        select(.apiVersion == "kustomize.toolkit.fluxcd.io/v1" and .kind == "Kustomization" and
          .metadata.name == strenv(KUSTOMIZATION))
      ' "${cluster_file}" >"${kustomization_file}"
      target="$(yq eval -r '.spec.path | sub("^\./"; "")' "${kustomization_file}")"
      manifest_file="${manifest_directory}/${target}.yaml"
      if [[ ! -f "${manifest_file}" ]]; then
        mkdir -p "$(dirname "${manifest_file}")"
        flux build kustomization "${name}" \
          --dry-run \
          --kustomization-file "${kustomization_file}" \
          --path "${target}" \
          --strict-substitute |
          yq eval '
            del(.metadata.labels."kustomize.toolkit.fluxcd.io/name", .metadata.labels."kustomize.toolkit.fluxcd.io/namespace") |
            del(.metadata.labels | select(length == 0))
          ' >"${manifest_file}"
      fi
    done
done
