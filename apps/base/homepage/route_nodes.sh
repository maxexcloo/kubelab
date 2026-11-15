#!/bin/sh
set -eu
inventory=${1:?Usage: route_nodes.sh inventory output}
output=${2:?Usage: route_nodes.sh inventory output}
temporary_directory=$(mktemp -d)
trap 'rm -fr "$temporary_directory"' EXIT

yq '
  .[] |= (.placementSelector = (.annotations."gethomepage.dev/pod-selector" //
    ("app.kubernetes.io/name=" + (.annotations."gethomepage.dev/app" //
      .labels."app.kubernetes.io/name" // .name))))
' "$inventory" > "$temporary_directory/routes.yaml"
yq -r '
  unique_by(.namespace + "/" + .placementSelector) | .[] |
  [.namespace, .placementSelector] | @tsv
' "$temporary_directory/routes.yaml" > "$temporary_directory/selectors.tsv"

# Ask Kubernetes to evaluate each distinct selector, including set expressions.
: > "$temporary_directory/nodes.json"
while IFS="$(printf '\t')" read -r namespace selector; do
  nodes=$("${KUBECTL:-kubectl}" --namespace "$namespace" get pods \
    --output 'jsonpath={range .items[?(@.status.phase=="Running")]}{.spec.nodeName}{"\n"}{end}{range .items[?(@.status.phase=="Pending")]}{.spec.nodeName}{"\n"}{end}' \
    --selector "$selector")
  NAMESPACE="$namespace" NODES="$nodes" SELECTOR="$selector" yq -n -I=0 -o=json '
    {(strenv(NAMESPACE)): {(strenv(SELECTOR)):
      (strenv(NODES) | split("\n") | map(select(. != "")) | unique | sort)}}
  ' >> "$temporary_directory/nodes.json"
done < "$temporary_directory/selectors.tsv"
# shellcheck disable=SC2016
yq ea -o=yaml -p=json '. as $placement ireduce ({}; . * $placement)' \
  "$temporary_directory/nodes.json" > "$temporary_directory/nodes.yaml"

# Look up placements directly, rather than scanning every selector for each route.
# shellcheck disable=SC2016
NODES="$temporary_directory/nodes.yaml" yq '
  load(strenv(NODES)) as $placements |
  .[] |= (.clusterGroups = ($placements[.namespace][.placementSelector] |
    with(select(length == 0); . = ["unscheduled"]) | map(strenv(HOMEPAGE_CLUSTER) + "/" + .)) |
    del(.placementSelector))
' "$temporary_directory/routes.yaml" > "$output"
