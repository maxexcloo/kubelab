#!/bin/sh
set -eu
inventory=${1:?Usage: route_nodes.sh inventory output}
output=${2:?Usage: route_nodes.sh inventory output}
temporary_directory=$(mktemp -d)
trap 'rm -fr "$temporary_directory"' EXIT
# Ask Kubernetes to evaluate selectors, including set expressions and app overrides.
yq -r '
  map(select(.cluster == strenv(HOMEPAGE_CLUSTER))) |
  map({"namespace": .namespace,
    "selector": (.annotations."gethomepage.dev/pod-selector" //
      ("app.kubernetes.io/name=" + (.annotations."gethomepage.dev/app" //
        .labels."app.kubernetes.io/name" // (.source | split("/") | .[2]))))}) |
  unique_by(.namespace + "/" + .selector) | .[] | [.namespace, .selector] | @tsv
' "$inventory" > "$temporary_directory/selectors.tsv"
: > "$temporary_directory/nodes.json"
while IFS="$(printf '\t')" read -r namespace selector; do
  nodes=$("${KUBECTL:-kubectl}" --namespace "$namespace" get pods \
    --output 'jsonpath={range .items[?(@.status.phase=="Running")]}{.spec.nodeName}{"\n"}{end}{range .items[?(@.status.phase=="Pending")]}{.spec.nodeName}{"\n"}{end}' \
    --selector "$selector")
  NAMESPACE="$namespace" NODES="$nodes" SELECTOR="$selector" yq -n -I=0 -o=json '
    {"namespace": strenv(NAMESPACE), "selector": strenv(SELECTOR),
     "nodes": (strenv(NODES) | split("\n") | map(select(. != "")) | unique | sort)}
  ' >> "$temporary_directory/nodes.json"
done < "$temporary_directory/selectors.tsv"
yq ea -o=yaml -p=json '[.]' "$temporary_directory/nodes.json" > "$temporary_directory/nodes.yaml"
# shellcheck disable=SC2016
NODES="$temporary_directory/nodes.yaml" yq '
  load(strenv(NODES)) as $placements |
  with(.[];
    .clusterGroups = [.cluster] |
    with(select(.cluster == strenv(HOMEPAGE_CLUSTER));
      . as $route |
      (.annotations."gethomepage.dev/pod-selector" //
        ("app.kubernetes.io/name=" + (.annotations."gethomepage.dev/app" //
          .labels."app.kubernetes.io/name" // (.source | split("/") | .[2])))) as $selector |
      ($placements | map(select(.namespace == $route.namespace and .selector == $selector)) | .[0].nodes) as $nodes |
      .clusterGroups = ($nodes | with(select(length == 0); . = ["unscheduled"]) |
        map($route.cluster + "-" + .))))
' "$inventory" > "$output"
