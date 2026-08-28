#!/usr/bin/env bash
set -euo pipefail

temporary_directory="$(mktemp -d "${TMPDIR:-/tmp}/kubelab-service-metadata.XXXXXX")"

cleanup() {
  rm -rf -- "${temporary_directory:?}"
}

trap cleanup EXIT

for cluster_directory in clusters/*; do
  cluster="${cluster_directory##*/}"
  inventory_file="${temporary_directory}/${cluster}.jsonl"
  : >"${inventory_file}"
  for target in "apps/overlays/${cluster}" "clusters/${cluster}/platform"; do
    # shellcheck disable=SC2016
    kustomize build "${target}" |
      yq eval -N -r '
        (
          (
            select(.kind == "HTTPRoute") |
            {
              "source": ("HTTPRoute/" + .metadata.namespace + "/" + .metadata.name),
              "annotations": (.metadata.annotations // {})
            }
          ),
          (
            select(.kind == "HelmRelease" and .spec.values.route.apiVersion == null) |
            .metadata as $metadata |
            (.spec.values.route // {} | to_entries[]) |
            select(.value.enabled // true) |
            {
              "source": (
                "HelmRelease/" + $metadata.namespace + "/" + $metadata.name +
                "/route/" + .key
              ),
              "annotations": (.value.annotations // {})
            }
          ),
          (
            select(.kind == "HelmRelease" and .spec.values.route.apiVersion != null) |
            {
              "source": (
                "HelmRelease/" + .metadata.namespace + "/" + .metadata.name + "/route"
              ),
              "annotations": (.spec.values.route.annotations // {})
            }
          )
        ) |
        select(.annotations."gethomepage.dev/enabled" == "true") |
        {
          "description": (.annotations."gethomepage.dev/description" // ""),
          "group": (.annotations."gethomepage.dev/group" // ""),
          "href": (.annotations."gethomepage.dev/href" // ""),
          "icon": (.annotations."gethomepage.dev/icon" // ""),
          "monitor": (
            .annotations."gethomepage.dev/siteMonitor" //
            .annotations."gethomepage.dev/href" //
            ""
          ),
          "name": (.annotations."gethomepage.dev/name" // ""),
          "source": .source
        } |
        @json
      ' - >>"${inventory_file}"
  done
  CLUSTER="${cluster}" jq -e -s '
    def missing_required:
      [.description, .group, .href, .icon, .monitor, .name] | any(. == "");
    def invalid_url:
      (.href | test("^https?://") | not) or
      (.monitor | test("^https?://") | not);
    . as $inventory |
    ($inventory | map(select(missing_required)) | map(.source)) as $missing |
    ($inventory | map(select(invalid_url)) | map(.source)) as $invalid |
    (
      $inventory |
      sort_by(.group, .name) |
      group_by(.group, .name) |
      map(select(length > 1) | map(.source) | join(", "))
    ) as $duplicates |
    if ($inventory | length) == 0 then
      error("cluster " + env.CLUSTER + " has no enabled service metadata")
    elif ($missing | length) > 0 then
      error("missing service metadata: " + ($missing | join(", ")))
    elif ($invalid | length) > 0 then
      error("invalid service URL: " + ($invalid | join(", ")))
    elif ($duplicates | length) > 0 then
      error("duplicate service group and name: " + ($duplicates | join("; ")))
    else
      true
    end
  ' "${inventory_file}" >/dev/null
done
