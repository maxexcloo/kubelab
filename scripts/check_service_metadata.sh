#!/usr/bin/env bash
set -euo pipefail

temporary_directory="$(mktemp -d "${TMPDIR:-/tmp}/kubelab-service-metadata.XXXXXX")"

cleanup() {
  rm -fr -- "${temporary_directory:?}"
}

trap cleanup EXIT

manifest_directory="${1:?Usage: check_service_metadata.sh <manifest-directory>}"

resources_file="${temporary_directory}/resources.jsonl"
route_file="${temporary_directory}/routes.json"
scripts/render_service_inventory.sh --all-routes --manifest-directory "${manifest_directory}" >"${route_file}"
: >"${resources_file}"
for cluster_file in "${manifest_directory}"/clusters/*.yaml; do
  cluster="$(basename "${cluster_file}" .yaml)"
  while IFS= read -r target; do
    CLUSTER="${cluster}" yq eval -I=0 -N -o=json '
      select(.kind == "Namespace" or .kind == "PocketIDClient" or .kind == "PrivateDNSRecord") |
      .cluster = strenv(CLUSTER)
    ' "${manifest_directory}/${target#./}.yaml" | sed '/^null$/d; /^$/d' >>"${resources_file}"
  done < <(
    yq eval -N -r 'select(.apiVersion == "kustomize.toolkit.fluxcd.io/v1" and .kind == "Kustomization") | .spec.path' "${cluster_file}" |
      sort -u
  )
done

jq -e \
  --slurpfile resources "${resources_file}" '
    ($resources | map(select(.kind == "Namespace") | {
      cluster, name: .metadata.name,
      privateAccess: (.metadata.labels."gateway.excloo.dev/private-access" // ""),
      publicAccess: (.metadata.labels."gateway.excloo.dev/public-access" // "")
    }) | unique_by(.cluster, .name)) as $namespaces |
    ($resources | map(select(.kind == "PocketIDClient") | {
      launchURL: .spec.client.launchURL,
      source: ("PocketIDClient/" + .metadata.name)
    })) as $pocket_id |
    ($resources | map(select(.kind == "PrivateDNSRecord") | {
      cluster, hostname: .spec.hostname, namespace: .metadata.namespace,
      composition: (.spec.crossplane.compositionRef.name // "private-dns-record"),
      source: ("PrivateDNSRecord/" + .metadata.namespace + "/" + .metadata.name)
    })) as $private_dns |
    def public_route:
      .parentRefs | any(. == "public-direct" or . == "public-tunnel");
    def tunnel_route:
      .parentRefs | any(. == "public-tunnel");
    def missing_required:
      [.monitor, .name] | any(. == "");
    def invalid_url:
      (.monitor | test("^https?://[^[:space:]]+$") | not);
    def url_hostname:
      try capture("^https?://(?<hostname>[^/:]+)").hostname catch "";
    . as $route_inventory |
    map(select(.monitoringEnabled)) as $inventory |
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
          $namespaces |
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
        select($namespaces | any(
          .cluster == $route.cluster and .name == $route.namespace and
          .privateAccess == "true"
        ) | not) | .source)
    ) as $missing_private_namespace_labels |
    ($inventory | map(select(missing_required)) | map(.source)) as $missing |
    ($inventory | map(select(invalid_url)) | map(.source)) as $invalid |
    (
      $inventory |
      map(select((.monitor | url_hostname) as $hostname | (.hostnames | index($hostname)) == null)) |
      map(.source)
    ) as $hostname_mismatches |
    (
      $inventory |
      sort_by(.cluster, .group, .name) |
      group_by(.cluster, .group, .name) |
      map(select(length > 1) | map(.source) | join(", "))
    ) as $duplicates |
    # External services such as Cloudflare Access have no route to match.
    ($route_inventory | map(.hostnames[] | split(".") | .[-2:] | join(".")) | unique) as $route_domains |
    (
      $pocket_id |
      map(select((.launchURL | url_hostname | split(".") | .[-2:] | join(".")) as $domain | $route_domains | index($domain))) |
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
    (
      $private_dns |
      map(. as $dns |
        ($route_inventory | any(
          .cluster == $dns.cluster and public_route and
          (.hostnames | index($dns.hostname)) != null
        )) as $public |
        select(
          if $public then .composition != "private-dns-record-control-d-only"
          else .composition != "private-dns-record"
          end
        ) |
        .source + " (" + .hostname + "): use " +
        (if $public then "private-dns-control-d-only for a public hostname"
         else "private-dns to publish a private hostname in Cloudflare" end)
      )
    ) as $incorrect_private_dns_compositions |
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
    elif ($incorrect_private_dns_compositions | length) > 0 then
      error("DNS publishing mode does not match route access: " + ($incorrect_private_dns_compositions | join("; ")))
    else
      true
    end
  ' "${route_file}" >/dev/null
