#!/usr/bin/env bash
set -euo pipefail

temporary_directory="$(mktemp -d "${TMPDIR:-/tmp}/kubelab-service-metadata.XXXXXX")"

cleanup() {
  rm -rf -- "${temporary_directory:?}"
}

trap cleanup EXIT

inventory_file="${temporary_directory}/inventory.json"
namespace_file="${temporary_directory}/namespaces.json"
namespace_lines_file="${temporary_directory}/namespaces.jsonl"
pocket_id_file="${temporary_directory}/pocket-id.json"
private_dns_file="${temporary_directory}/private-dns.json"
route_file="${temporary_directory}/routes.json"

scripts/render_service_inventory.sh >"${inventory_file}"
scripts/render_service_inventory.sh --all-routes >"${route_file}"

: >"${namespace_lines_file}"
while IFS= read -r cluster_directory; do
  cluster="${cluster_directory##*/}"
  for target in "apps/overlays/${cluster}" "clusters/${cluster}/platform"; do
    kustomize build "${target}" |
      CLUSTER="${cluster}" yq eval -N -o=json -I=0 '
        select(.kind == "Namespace") |
        {
          "cluster": strenv(CLUSTER),
          "name": .metadata.name,
          "publicAccess": (
            .metadata.labels."gateway.excloo.dev/public-access" // ""
          )
        }
      ' - | sed '/^null$/d; /^$/d' >>"${namespace_lines_file}"
  done
done < <(find clusters -mindepth 1 -maxdepth 1 -type d | sort)
jq -s 'unique_by(.cluster, .name)' "${namespace_lines_file}" >"${namespace_file}"

yq eval -N -o=json -I=0 '
  select(.kind == "PocketIDClient") |
  {
    "launchURL": .spec.client.launchURL,
    "source": ("PocketIDClient/" + .metadata.namespace + "/" + .metadata.name)
  }
' apps/integrations/pocket-id/*.yaml | jq -s '.' >"${pocket_id_file}"

yq eval -N -o=json -I=0 '
  select(.kind == "PrivateDNSRecord") |
  {
    "hostname": .spec.hostname,
    "source": ("PrivateDNSRecord/" + .metadata.namespace + "/" + .metadata.name)
  }
' apps/integrations/private-dns/*.yaml | jq -s '.' >"${private_dns_file}"

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
      [$inventory[] | select(.cluster == "mbk") | .hostnames[]] as $hostnames |
      $private_dns[0] |
      map(select(.hostname as $hostname | $hostnames | index($hostname) | not)) |
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
      error("private DNS hostname has no enabled mbk route: " + ($missing_private_dns_routes | join(", ")))
    else
      true
    end
  ' "${inventory_file}" >/dev/null
