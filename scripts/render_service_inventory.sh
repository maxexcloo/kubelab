#!/usr/bin/env bash
set -euo pipefail

# Flylab's Gatus renderer consumes this inventory.
all_routes=false
manifest_directory=""

usage() {
  echo "Usage: $0 [--all-routes] [--manifest-directory directory]" >&2
}

while (($# > 0)); do
  case "$1" in
    --all-routes)
      all_routes=true
      ;;
    --manifest-directory)
      manifest_directory="${2:?--manifest-directory requires a directory}"
      shift
      ;;
    *)
      usage
      exit 2
      ;;
  esac
  shift
done

temporary_directory="$(mktemp -d "${TMPDIR:-/tmp}/kubelab-service-inventory.XXXXXX")"
trap 'rm -fr -- "${temporary_directory:?}"' EXIT

if [[ -z "${manifest_directory}" ]]; then
  manifest_directory="${temporary_directory}/manifests"
  scripts/render_manifests.sh "${manifest_directory}"
fi

inventory_file="${temporary_directory}/inventory.jsonl"
secret_file="${temporary_directory}/secrets.jsonl"
: >"${inventory_file}"
: >"${secret_file}"

for cluster_file in "${manifest_directory}"/clusters/*.yaml; do
  cluster="$(basename "${cluster_file}" .yaml)"
  while IFS= read -r target; do
    target="${target#./}"
    ALL_ROUTES="${all_routes}" CLUSTER="${cluster}" yq eval --from-file scripts/service_routes.yq -I=0 -N -o=json \
      "${manifest_directory}/${target}.yaml" | sed '/^null$/d; /^$/d' >>"${inventory_file}"
    CLUSTER="${cluster}" yq eval -I=0 -N -o=json '
      select(.kind == "ClusterSecretStore" or .kind == "CloudflareAccessApplication" or .kind == "ExternalSecret" or .kind == "SecretStore") |
      .cluster = strenv(CLUSTER)
    ' "${manifest_directory}/${target}.yaml" | sed '/^null$/d; /^$/d' >>"${secret_file}"
  done < <(
    yq eval -N -r 'select(.apiVersion == "kustomize.toolkit.fluxcd.io/v1" and .kind == "Kustomization") | .spec.path' "${cluster_file}" |
      sort -u
  )
done

jq -s --slurpfile resources "${secret_file}" --from-file scripts/monitoring_headers.jq "${inventory_file}"
