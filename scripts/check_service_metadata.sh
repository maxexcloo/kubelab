#!/usr/bin/env bash
set -euo pipefail

temporary_directory="$(mktemp -d "${TMPDIR:-/tmp}/kubelab-service-metadata.XXXXXX")"

cleanup() {
  rm -rf -- "${temporary_directory:?}"
}

trap cleanup EXIT

manifest_directory="${1:?Usage: check_service_metadata.sh <manifest-directory>}"

inventory_file="${temporary_directory}/inventory.json"
namespace_file="${temporary_directory}/namespaces.json"
namespace_lines_file="${temporary_directory}/namespaces.jsonl"
pocket_id_file="${temporary_directory}/pocket-id.json"
private_dns_file="${temporary_directory}/private-dns.json"
route_file="${temporary_directory}/routes.json"

scripts/render_service_inventory.sh --manifest-directory "${manifest_directory}" >"${inventory_file}"
scripts/render_service_inventory.sh --manifest-directory "${manifest_directory}" --all-routes >"${route_file}"

: >"${namespace_lines_file}"
: >"${private_dns_file}"
manifest_files=()
while IFS= read -r cluster_directory; do
  cluster="${cluster_directory##*/}"
  while IFS= read -r target; do
    manifest_file="${manifest_directory}/${target#./}.yaml"
    manifest_files+=("${manifest_file}")
    CLUSTER="${cluster}" yq eval -N -o=json -I=0 '
        select(.kind == "Namespace") |
        {
          "cluster": strenv(CLUSTER),
          "name": .metadata.name,
          "privateAccess": (.metadata.labels."gateway.excloo.dev/private-access" // ""),
          "publicAccess": (
            .metadata.labels."gateway.excloo.dev/public-access" // ""
          )
        }
      ' "${manifest_file}" | sed '/^null$/d; /^$/d' >>"${namespace_lines_file}"
    CLUSTER="${cluster}" yq eval -N -o=json -I=0 '
      select(.kind == "PrivateDNSRecord") |
      {
        "cluster": strenv(CLUSTER),
        "hostname": .spec.hostname,
        "namespace": .metadata.namespace,
        "source": ("PrivateDNSRecord/" + .metadata.namespace + "/" + .metadata.name)
      }
    ' "${manifest_file}" | sed '/^null$/d; /^$/d' >>"${private_dns_file}"
  done < <(
    yq eval -N -r 'select(.apiVersion == "kustomize.toolkit.fluxcd.io/v1" and .spec.sourceRef.name == "flux-system") | .spec.path' "${manifest_directory}/clusters/${cluster}.yaml" |
      sort -u
  )
done < <(find clusters -mindepth 1 -maxdepth 1 -type d | sort)
jq -s 'unique_by(.cluster, .name)' "${namespace_lines_file}" >"${namespace_file}"

yq eval -N -o=json -I=0 '
  select(.kind == "PocketIDClient") |
  {
    "launchURL": .spec.client.launchURL,
    "source": ("PocketIDClient/" + .metadata.namespace + "/" + .metadata.name)
  }
' "${manifest_files[@]}" | jq -s '.' >"${pocket_id_file}"

# Match Homepage's native weight-then-name ordering in every cluster.
CLUSTER='' yq -N -o=json -I=0 --from-file apps/base/homepage/service_routes.yq "${manifest_files[@]}" |
  jq -s -e '
    map(select(.annotations."gethomepage.dev/enabled" == "true")) |
    map(select(
      (.annotations."gethomepage.dev/weight" // "0") !=
      (if (.annotations | keys | any(test("^gethomepage\\.dev/widgets?\\."))) then "-100" else "0" end)
    ) | .source) |
    if length == 0 then true else error("Homepage widget ordering: " + join(", ")) end
  ' >/dev/null

jq -e \
  --slurpfile namespaces "${namespace_file}" \
  --slurpfile pocket_id "${pocket_id_file}" \
  --slurpfile private_dns "${private_dns_file}" \
  --slurpfile routes "${route_file}" '
    def public_route:
      .parentRefs | any(. == "public-direct" or . == "public-tunnel");
    def tunnel_route:
      .parentRefs | any(. == "public-tunnel");
    def missing_required:
      [.description, .group, .href, .icon, .monitor, .name] | any(. == "");
    def invalid_url:
      (.href | test("^https?://[^[:space:]]+$") | not) or
      (.monitor | test("^https?://[^[:space:]]+$") | not);
    def url_hostname:
      try capture("^https?://(?<hostname>[^/:]+)").hostname catch "";
    . as $inventory |
    $routes[0] as $route_inventory |
    (
      $route_inventory |
      map(select(public_route and .publicAccess != "true") | .source)
    ) as $missing_public_route_labels |
    (
      $route_inventory |
      map(select(tunnel_route and .cloudflareProxied != "true") | .source)
    ) as $missing_tunnel_proxy_annotations |
    (
      $route_inventory |
      map(select((public_route | not) and .publicAccess == "true") | .source)
    ) as $unexpected_public_route_labels |
    (
      $route_inventory |
      map(
        select(public_route) |
        . as $route |
        select(
          $namespaces[0] |
          any(
            .cluster == $route.cluster and
            .name == $route.namespace and
            .publicAccess == "true"
          ) |
          not
        ) |
        .source
      )
    ) as $missing_public_namespace_labels |
    (
      $route_inventory |
      map(select((.parentRefs | index("private")) != null) |
        . as $route |
        select($namespaces[0] | any(
          .cluster == $route.cluster and .name == $route.namespace and
          .privateAccess == "true"
        ) | not) | .source)
    ) as $missing_private_namespace_labels |
    ($inventory | map(select(missing_required)) | map(.source)) as $missing |
    ($inventory | map(select(invalid_url)) | map(.source)) as $invalid |
    (
      $inventory |
      map(select((.href | url_hostname) as $hostname | (.hostnames | index($hostname)) == null)) |
      map(.source)
    ) as $hostname_mismatches |
    (
      $inventory |
      sort_by(.cluster, .group, .name) |
      group_by(.cluster, .group, .name) |
      map(select(length > 1) | map(.source) | join(", "))
    ) as $duplicates |
    (
      $pocket_id[0] |
      map(select(.launchURL as $url | $inventory | any(.href == $url) | not)) |
      map(.source)
    ) as $missing_pocket_id_routes |
    (
      $private_dns |
      map(select(. as $dns | $route_inventory | any(
        .cluster == $dns.cluster and
        .namespace == $dns.namespace and
        (.parentRefs | index("private")) != null and
        (.hostnames | index($dns.hostname)) != null
      ) | not)) |
      map(.source)
    ) as $missing_private_dns_routes |
    ($inventory | map(.cluster) | unique) as $clusters |
    if ($clusters | length) == 0 then
      error("service inventory is empty")
    elif ($missing_public_route_labels | length) > 0 then
      error("public route missing public-access label: " + ($missing_public_route_labels | join(", ")))
    elif ($missing_public_namespace_labels | length) > 0 then
      error("public route namespace missing public-access label: " + ($missing_public_namespace_labels | join(", ")))
    elif ($missing_tunnel_proxy_annotations | length) > 0 then
      error("public-tunnel route missing Cloudflare proxy annotation: " + ($missing_tunnel_proxy_annotations | join(", ")))
    elif ($unexpected_public_route_labels | length) > 0 then
      error("non-public route has public-access label: " + ($unexpected_public_route_labels | join(", ")))
    elif ($missing_private_namespace_labels | length) > 0 then
      error("private route namespace missing private-access label: " + ($missing_private_namespace_labels | join(", ")))
    elif ($inventory | any(.alerts != "true" and .alerts != "false")) then
      error("monitoring alerts must be true or false")
    elif ($missing | length) > 0 then
      error("missing service metadata: " + ($missing | join(", ")))
    elif ($invalid | length) > 0 then
      error("invalid service URL: " + ($invalid | join(", ")))
    elif ($hostname_mismatches | length) > 0 then
      error("service href does not match a route hostname: " + ($hostname_mismatches | join(", ")))
    elif ($duplicates | length) > 0 then
      error("duplicate cluster, service group and name: " + ($duplicates | join("; ")))
    elif ($missing_pocket_id_routes | length) > 0 then
      error("Pocket ID launch URL has no enabled route: " + ($missing_pocket_id_routes | join(", ")))
    elif ($missing_private_dns_routes | length) > 0 then
      error("private DNS hostname has no matching private route: " + ($missing_private_dns_routes | join(", ")))
    else
      true
    end
  ' "${inventory_file}" >/dev/null
