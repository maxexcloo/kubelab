#!/usr/bin/env bash
set -euo pipefail

# Flylab's Gatus renderer consumes this inventory and --manifest-directory.
all_routes=false
clusters=()
manifest_directory=""

usage() {
  echo "Usage: $0 [--all-routes] [--manifest-directory directory] [cluster ...]" >&2
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
    -*)
      usage
      exit 2
      ;;
    *)
      clusters+=("$1")
      ;;
  esac
  shift
done

if ((${#clusters[@]} == 0)); then
  while IFS= read -r cluster_directory; do
    clusters+=("${cluster_directory##*/}")
  done < <(find clusters -maxdepth 1 -mindepth 1 -type d | sort)
fi

temporary_directory="$(mktemp -d "${TMPDIR:-/tmp}/kubelab-service-inventory.XXXXXX")"

cleanup() {
  rm -fr -- "${temporary_directory:?}"
}

trap cleanup EXIT

if [[ -z "${manifest_directory}" ]]; then
  manifest_directory="${temporary_directory}/manifests"
  scripts/render_manifests.sh "${manifest_directory}" "${clusters[@]}"
fi

inventory_file="${temporary_directory}/inventory.jsonl"
secret_file="${temporary_directory}/secrets.jsonl"
: >"${inventory_file}"
: >"${secret_file}"

for cluster in "${clusters[@]}"; do
  if [[ ! -d "apps/overlays/${cluster}" || ! -d "clusters/${cluster}/platform" ]]; then
    echo "Unknown or incomplete cluster: ${cluster}" >&2
    exit 2
  fi
  for target in "apps/overlays/${cluster}" "clusters/${cluster}/platform"; do
    # shellcheck disable=SC2016
    ALL_ROUTES="${all_routes}" CLUSTER="${cluster}" yq eval --from-file scripts/service-routes/service_routes.yq -I=0 -N -o=json \
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
  done
done

jq -s --slurpfile resources "${secret_file}" --from-file scripts/service-routes/monitoring_headers.jq "${inventory_file}"
