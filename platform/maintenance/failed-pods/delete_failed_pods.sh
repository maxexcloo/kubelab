#!/bin/sh
set -eu
# Deployments replace pods that fail on node shutdown or eviction but never
# delete them, and pod garbage collection waits for thousands of terminated pods.
# StatefulSet and DaemonSet controllers delete their own failed pods; Job pods
# keep their history.
kubectl get pods --all-namespaces --field-selector=status.phase=Failed --output=json |
  jq -r '.items[] | select(any(.metadata.ownerReferences[]?; .kind == "ReplicaSet")) |
    "\(.metadata.namespace) \(.metadata.name)"' |
  while read -r namespace name; do
    kubectl --namespace "$namespace" delete pod "$name" --ignore-not-found
  done
