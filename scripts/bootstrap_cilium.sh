#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 0 ]]; then
  echo "Usage: mise run bootstrap-cilium" >&2
  exit 1
fi

cluster="$(kubectl config current-context)"
repository_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
release_file="${repository_dir}/platform/networking/cilium/helm-release.yaml"
repository_file="${repository_dir}/platform/sources/cilium/helm-repository.yaml"

if [[ ! -d "${repository_dir}/clusters/${cluster}" ]]; then
  echo "error: cluster '${cluster}' is not defined under clusters/." >&2
  exit 1
fi

api_server="$(kubectl --context "${cluster}" config view --minify -o jsonpath='{.clusters[0].cluster.server}')"
echo "Cluster: ${cluster}"
echo "API server: ${api_server}"
read -r -p "Bootstrap Cilium on cluster '${cluster}'? [y/N] " confirmation
if [[ ! "${confirmation}" =~ ^[Yy]$ ]]; then
  echo "Cancelled."
  exit 1
fi

chart="$(yq -er '.spec.chart.spec.chart' "${release_file}")"
release="$(yq -er '.spec.releaseName' "${release_file}")"
repository="$(yq -er '.spec.url' "${repository_file}")"
version="$(yq -er '.spec.chart.spec.version' "${release_file}")"

helm upgrade --install "${release}" "${chart}" \
  --kube-context "${cluster}" \
  --namespace kube-system \
  --repo "${repository}" \
  --timeout 10m \
  --values <(yq eval '.spec.values' "${release_file}") \
  --version "${version}" \
  --wait
kubectl --context "${cluster}" wait nodes --all --for=condition=Ready --timeout=10m
