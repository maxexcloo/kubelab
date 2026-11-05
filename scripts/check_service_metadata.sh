#!/usr/bin/env bash
set -euo pipefail

temporary_directory="$(mktemp -d "${TMPDIR:-/tmp}/kubelab-service-metadata.XXXXXX")"
trap 'rm -fr -- "${temporary_directory:?}"' EXIT

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
    def invalid_href:
      (.href | test("^[a-z][a-z0-9+.-]*://[^/]*\\.invalid([/:]|$)"));
    def url_hostname:
      try capture("^https?://(?<hostname>[^/:]+)").hostname catch "";
    map(select(.type != "certificate")) as $route_inventory |
    map(select(.monitoringEnabled)) as $inventory |
    # Route domains limit the Pocket ID check; external services such as
    # Cloudflare Access have no route to match.
    ($route_inventory | map(.hostnames[] | split(".") | .[-2:] | join(".")) | unique) as $route_domains |
    def failure($message; $separator; $sources):
      if ($sources | length) > 0 then $message + ": " + ($sources | join($separator)) else empty end;
    if ($inventory | length) == 0 then error("service inventory is empty") else . end |
    [
      failure("public route missing public-access label"; ", ";
        $route_inventory | map(select(public_route and .publicAccess != "true") | .source)),
      failure("public route namespace missing public-access label"; ", ";
        $route_inventory | map(select(public_route) | . as $route |
          select($namespaces | any(
            .cluster == $route.cluster and .name == $route.namespace and .publicAccess == "true"
          ) | not) | .source)),
      failure("public-tunnel route missing Cloudflare proxy annotation"; ", ";
        $route_inventory | map(select(tunnel_route and .cloudflareProxied != "true") | .source)),
      failure("non-public route has public-access label"; ", ";
        $route_inventory | map(select((public_route | not) and .publicAccess == "true") | .source)),
      failure("private route namespace missing private-access label"; ", ";
        $route_inventory | map(select((.parentRefs | index("private")) != null) | . as $route |
          select($namespaces | any(
            .cluster == $route.cluster and .name == $route.namespace and .privateAccess == "true"
          ) | not) | .source)),
      failure("monitoring alerts must be true or false"; ", ";
        $inventory | map(select(.alerts != "true" and .alerts != "false") | .source)),
      failure("missing service metadata"; ", "; $inventory | map(select(missing_required) | .source)),
      failure("invalid service URL"; ", "; $inventory | map(select(invalid_url) | .source)),
      failure("unresolved service href placeholder"; ", "; $route_inventory | map(select(invalid_href) | .source)),
      failure("service href does not match a route hostname"; ", ";
        $inventory | map(select((.monitor | url_hostname) as $hostname | (.hostnames | index($hostname)) == null) | .source)),
      failure("duplicate cluster, service group and name"; "; ";
        $inventory | sort_by(.cluster, .group, .name) | group_by(.cluster, .group, .name) |
          map(select(length > 1) | map(.source) | join(", "))),
      failure("Pocket ID launch URL has no enabled route"; ", ";
        $pocket_id |
          map(select((.launchURL | url_hostname | split(".") | .[-2:] | join(".")) as $domain | $route_domains | index($domain))) |
          map(select(.launchURL as $url | $inventory | any(.href == $url) | not) | .source)),
      failure("private DNS hostname has no matching private route"; ", ";
        $private_dns | map(select(. as $dns | $route_inventory | any(
          .cluster == $dns.cluster and .namespace == $dns.namespace and
          (.parentRefs | index("private")) != null and
          (.hostnames | index($dns.hostname)) != null
        ) | not) | .source)),
      failure("DNS publishing mode does not match route access"; "; ";
        $private_dns | map(. as $dns |
          ($route_inventory | any(
            .cluster == $dns.cluster and public_route and (.hostnames | index($dns.hostname)) != null
          )) as $public |
          select(
            if $public then .composition != "private-dns-record-control-d-only"
            else .composition != "private-dns-record"
            end
          ) |
          .source + " (" + .hostname + "): use " +
          (if $public then "private-dns-control-d-only for a public hostname"
           else "private-dns to publish a private hostname in Cloudflare" end)))
    ] |
    if length > 0 then error(join("\n")) else true end
  ' "${route_file}" >/dev/null
