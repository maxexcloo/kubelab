#!/usr/bin/env bash
set -euo pipefail

all_routes=false
clusters=()
include_static=false

usage() {
  echo "Usage: $0 [--all-routes] [--include-static] [cluster ...]" >&2
}

while (($# > 0)); do
  case "$1" in
    --all-routes)
      all_routes=true
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

inventory_file="${temporary_directory}/inventory.jsonl"
: >"${inventory_file}"

for cluster in "${clusters[@]}"; do
  if [[ ! -d "apps/overlays/${cluster}" || ! -d "clusters/${cluster}/platform" ]]; then
    echo "Unknown or incomplete cluster: ${cluster}" >&2
    exit 2
  fi
  for target in "apps/overlays/${cluster}" "clusters/${cluster}/platform"; do
    # shellcheck disable=SC2016
    kustomize build "${target}" |
      ALL_ROUTES="${all_routes}" CLUSTER="${cluster}" yq eval -N -r '
        (
          (
            select(.kind == "HTTPRoute") |
            {
              "annotations": (.metadata.annotations // {}),
              "hostnames": (.spec.hostnames // []),
              "labels": (.metadata.labels // {}),
              "namespace": .metadata.namespace,
              "parentRefs": ((.spec.parentRefs // []) | map(.name)),
              "source": ("HTTPRoute/" + .metadata.namespace + "/" + .metadata.name)
            }
          ),
          (
            select(.kind == "HelmRelease" and .spec.values.route.apiVersion == null) |
            .metadata as $metadata |
            (.spec.values.route // {} | to_entries[]) |
            select(.value.enabled != false) |
            {
              "annotations": (.value.annotations // {}),
              "hostnames": (.value.hostnames // []),
              "labels": (.value.labels // {}),
              "namespace": $metadata.namespace,
              "parentRefs": ((.value.parentRefs // []) | map(.name)),
              "source": (
                "HelmRelease/" + $metadata.namespace + "/" + $metadata.name +
                "/route/" + .key
              )
            }
          ),
          (
            select(
              .kind == "HelmRelease" and
              .spec.values.route.apiVersion != null and
              .spec.values.route.enabled != false
            ) |
            {
              "annotations": (.spec.values.route.annotations // {}),
              "hostnames": (.spec.values.route.hostnames // []),
              "labels": (.spec.values.route.labels // {}),
              "namespace": .metadata.namespace,
              "parentRefs": ((.spec.values.route.parentRefs // []) | map(.name)),
              "source": (
                "HelmRelease/" + .metadata.namespace + "/" + .metadata.name + "/route"
              )
            }
          )
        ) |
        select(
          strenv(ALL_ROUTES) == "true" or
          .annotations."gethomepage.dev/enabled" == "true"
        ) |
        {
          "cluster": strenv(CLUSTER),
          "cloudflareProxied": (
            .annotations."external-dns.alpha.kubernetes.io/cloudflare-proxied" //
            ""
          ),
          "description": (.annotations."gethomepage.dev/description" // ""),
          "group": (.annotations."gethomepage.dev/group" // ""),
          "hostnames": .hostnames,
          "href": (.annotations."gethomepage.dev/href" // ""),
          "icon": (.annotations."gethomepage.dev/icon" // ""),
          "monitor": (
            .annotations."gethomepage.dev/siteMonitor" //
            .annotations."gethomepage.dev/href" //
            ""
          ),
          "name": (.annotations."gethomepage.dev/name" // ""),
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
  yq -r '.data."services.yaml"' apps/base/homepage/config-map.yaml |
    yq -o=json '.' - |
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
