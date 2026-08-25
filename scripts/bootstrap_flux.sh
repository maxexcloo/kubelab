#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: mise run bootstrap-flux <cluster>" >&2
  exit 1
fi

cluster="$1"
repository_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cluster_dir="${repository_dir}/clusters/${cluster}"
release_file="${repository_dir}/platform/observability/victoria-metrics-k8s-stack/helm-release.yaml"

if [[ ! -d "${cluster_dir}" ]]; then
  echo "error: cluster '${cluster}' is not defined under clusters/." >&2
  exit 1
fi

source="$(yq -er '.spec.chart.spec.sourceRef.name' "${release_file}")"
repository_file="${repository_dir}/platform/sources/${source}/helm-repository.yaml"
chart="$(yq -er '.spec.chart.spec.chart' "${release_file}")"
repository="$(yq -er '.spec.url' "${repository_file}")"
version="$(yq -er '.spec.chart.spec.version' "${release_file}")"

helm show crds "${chart}" --repo "${repository}" --version "${version}" |
  kubectl --context "${cluster}" apply --filename -
kubectl --context "${cluster}" apply \
  --field-manager=kubelab-bootstrap \
  --force-conflicts \
  --server-side \
  --kustomize "${cluster_dir}/flux-system"
kubectl --context "${cluster}" -n flux-system wait deployment --all \
  --for=condition=Available \
  --timeout=5m
flux --context "${cluster}" reconcile kustomization flux-system --with-source
flux --context "${cluster}" get kustomizations
