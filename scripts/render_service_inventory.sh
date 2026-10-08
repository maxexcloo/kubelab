#!/usr/bin/env bash
set -euo pipefail

all_routes=false
clusters=()
include_static=false
manifest_directory=""

usage() {
  echo "Usage: $0 [--all-routes] [--include-static] [--manifest-directory directory] [cluster ...]" >&2
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
    --include-static)
      include_static=true
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
  done < <(find clusters -mindepth 1 -maxdepth 1 -type d | sort)
fi

temporary_directory="$(mktemp -d "${TMPDIR:-/tmp}/kubelab-service-inventory.XXXXXX")"

cleanup() {
  rm -rf -- "${temporary_directory:?}"
}

trap cleanup EXIT

if [[ -z "${manifest_directory}" ]]; then
  manifest_directory="${temporary_directory}/manifests"
  scripts/render_manifests.sh "${manifest_directory}" "${clusters[@]}"
fi

inventory_file="${temporary_directory}/inventory.jsonl"
: >"${inventory_file}"

for cluster in "${clusters[@]}"; do
  if [[ ! -d "apps/overlays/${cluster}" || ! -d "clusters/${cluster}/platform" ]]; then
    echo "Unknown or incomplete cluster: ${cluster}" >&2
    exit 2
  fi
  for target in "apps/overlays/${cluster}" "clusters/${cluster}/platform"; do
    # shellcheck disable=SC2016
    ALL_ROUTES="${all_routes}" CLUSTER="${cluster}" yq eval -N -o=json -I=0 --from-file apps/base/homepage/service_routes.yq \
      "${manifest_directory}/${target}.yaml" |
      ALL_ROUTES="${all_routes}" CLUSTER="${cluster}" yq eval -N -p=json -o=yaml -r '
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
  done
done

if [[ "${include_static}" == true ]]; then
  sh apps/base/homepage/render_services.sh \
    apps/base/homepage/services.yaml "${temporary_directory}/services.yaml" \
    "${HOMELAB_DIRECTORY:-}"
  yq -o=json '.' "${temporary_directory}/services.yaml" |
    jq -c '
      .[] |
      to_entries[] as $group |
      $group.value[] |
      to_entries[] |
      select(.value.siteMonitor != null) |
      {
        cluster: null,
        cloudflareProxied: "",
        description: (.value.description // ""),
        group: $group.key,
        hostnames: [],
        href: (.value.href // ""),
        icon: (.value.icon // ""),
        monitor: .value.siteMonitor,
        name: .key,
        namespace: null,
        parentRefs: [],
        publicAccess: "",
        source: ("Homepage/services/" + $group.key + "/" + .key),
        type: "homepage"
      }
    ' >>"${inventory_file}"
fi

jq -s 'sort_by(.cluster // "", .group, .name, .source)' "${inventory_file}"
