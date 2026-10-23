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

cleanup() {
  rm -fr -- "${temporary_directory:?}"
}

trap cleanup EXIT

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
    # shellcheck disable=SC2016
    ALL_ROUTES="${all_routes}" CLUSTER="${cluster}" yq eval --from-file apps/base/homepage/service_routes.yq -I=0 -N -o=json \
      "${manifest_directory}/${target}.yaml" |
      ALL_ROUTES="${all_routes}" CLUSTER="${cluster}" yq eval -N -o=yaml -p=json -r '
        select(
          strenv(ALL_ROUTES) == "true" or
          .annotations."monitoring.excloo.dev/enabled" == "true"
        ) |
        {
          "alerts": (.annotations."monitoring.excloo.dev/alerts" // "true"),
          "cluster": strenv(CLUSTER),
          "cloudflareProxied": (
            .annotations."external-dns.alpha.kubernetes.io/cloudflare-proxied" //
            ""
          ),
          "description": (.annotations."gethomepage.dev/description" // ""),
          "group": (.annotations."gethomepage.dev/group" // "Services"),
          "headers": ((.annotations."monitoring.excloo.dev/headers" // "{}") | from_json),
          "hostnames": .hostnames,
          "href": (.annotations."gethomepage.dev/href" // ""),
          "icon": (.annotations."gethomepage.dev/icon" // ""),
          "monitor": (
            .annotations."monitoring.excloo.dev/url" //
            ("https://" + (.hostnames[0] // "") + (.annotations."monitoring.excloo.dev/path" // ""))
          ),
          "monitoringEnabled": (.annotations."monitoring.excloo.dev/enabled" == "true"),
          "name": (.annotations."monitoring.excloo.dev/name" // .annotations."gethomepage.dev/name" // (.source | split("/") | .[2])),
          "namespace": .namespace,
          "parentRefs": .parentRefs,
          "publicAccess": (.labels."gateway.excloo.dev/public-access" // ""),
          "source": .source,
          "type": "route"
        } |
        select(.source != null) |
        @json
      ' - | sed '/^null$/d; /^$/d' >>"${inventory_file}"
    CLUSTER="${cluster}" yq eval -I=0 -N -o=json '
      select(.kind == "ClusterSecretStore" or .kind == "ExternalSecret" or .kind == "SecretStore") |
      .cluster = strenv(CLUSTER)
    ' "${manifest_directory}/${target}.yaml" | sed '/^null$/d; /^$/d' >>"${secret_file}"
  done < <(
    yq eval -N -r 'select(.apiVersion == "kustomize.toolkit.fluxcd.io/v1" and .kind == "Kustomization") | .spec.path' "${cluster_file}" |
      sort -u
  )
done

jq -s --slurpfile resources "${secret_file}" --from-file scripts/monitoring_headers.jq "${inventory_file}"
