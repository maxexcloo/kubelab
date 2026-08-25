#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: mise run bootstrap-cluster <cluster> [--yes]" >&2
}

cluster=""
assume_yes=false

for argument in "$@"; do
  case "${argument}" in
    --help|-h)
      usage
      exit 0
      ;;
    --yes)
      assume_yes=true
      ;;
    -*)
      echo "error: unknown option '${argument}'." >&2
      usage
      exit 1
      ;;
    *)
      if [[ -n "${cluster}" ]]; then
        echo "error: only one cluster may be selected." >&2
        usage
        exit 1
      fi
      cluster="${argument}"
      ;;
  esac
done

if [[ -z "${cluster}" ]]; then
  usage
  exit 1
fi

if [[ ! "${cluster}" =~ ^[a-z0-9][a-z0-9-]*$ ]]; then
  echo "error: invalid cluster name '${cluster}'." >&2
  exit 1
fi

repository_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cluster_dir="${repository_dir}/clusters/${cluster}"

if [[ ! -d "${cluster_dir}" ]]; then
  echo "error: cluster '${cluster}' is not defined under clusters/." >&2
  exit 1
fi

for tool in flux helm kubectl yq; do
  if ! command -v "${tool}" >/dev/null 2>&1; then
    echo "error: ${tool} is required but not found in PATH." >&2
    exit 1
  fi
done

if [[ "$(kubectl config get-contexts "${cluster}" -o name)" != "${cluster}" ]]; then
  echo "error: kubeconfig context '${cluster}' does not exist." >&2
  exit 1
fi

api_server="$(kubectl --context "${cluster}" config view --minify -o jsonpath='{.clusters[0].cluster.server}')"
nodes="$(kubectl --context "${cluster}" get nodes -o custom-columns='NAME:.metadata.name,READY:.status.conditions[?(@.type=="Ready")].status' --no-headers)"

echo "Cluster: ${cluster}"
echo "Context: ${cluster}"
echo "API server: ${api_server}"
echo "Nodes:"
echo "${nodes}"

if [[ "${assume_yes}" == false ]]; then
  if [[ ! -t 0 ]]; then
    echo "error: confirmation requires a terminal; pass --yes for non-interactive use." >&2
    exit 1
  fi
  read -r -p "Bootstrap and reconcile cluster '${cluster}'? [y/N] " confirmation
  if [[ ! "${confirmation}" =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 0
  fi
fi

if ! kubectl --context "${cluster}" -n external-secrets get secret onepassword-connect >/dev/null 2>&1; then
  echo "error: the homelab credential bootstrap has not injected secret external-secrets/onepassword-connect." >&2
  exit 1
fi

cilium_release_file="${repository_dir}/platform/networking/cilium/helm-release.yaml"
cilium_kustomization_file="${repository_dir}/platform/networking/cilium/kustomization.yaml"
cilium_chart="$(yq -er '.spec.chart.spec.chart' "${cilium_release_file}")"
cilium_release="$(yq -er '.spec.releaseName' "${cilium_release_file}")"
cilium_resource="$(yq -er '.metadata.name' "${cilium_release_file}")"
cilium_source="$(yq -er '.spec.chart.spec.sourceRef.name' "${cilium_release_file}")"
cilium_version="$(yq -er '.spec.chart.spec.version' "${cilium_release_file}")"
cilium_namespace="$(yq -er '.namespace' "${cilium_kustomization_file}")"
cilium_repository_file="${repository_dir}/platform/sources/${cilium_source}/helm-repository.yaml"
cilium_repository="$(yq -er '.spec.url' "${cilium_repository_file}")"

if kubectl --context "${cluster}" -n "${cilium_namespace}" get helmrelease "${cilium_resource}" >/dev/null 2>&1; then
  echo "Cilium is managed by Flux; leaving it under Flux ownership."
else
  echo "Installing ${cilium_chart} ${cilium_version}..."
  helm repo add "${cilium_source}" "${cilium_repository}" --force-update
  helm upgrade --install "${cilium_release}" "${cilium_source}/${cilium_chart}" \
    --kube-context "${cluster}" \
    --namespace "${cilium_namespace}" \
    --version "${cilium_version}" \
    --values <(yq eval '.spec.values' "${cilium_release_file}") \
    --wait \
    --timeout 10m
fi
kubectl --context "${cluster}" wait nodes --all --for=condition=Ready --timeout=10m

victoria_metrics_release_file="${repository_dir}/platform/observability/victoria-metrics-k8s-stack/helm-release.yaml"
victoria_metrics_chart="$(yq -er '.spec.chart.spec.chart' "${victoria_metrics_release_file}")"
victoria_metrics_source="$(yq -er '.spec.chart.spec.sourceRef.name' "${victoria_metrics_release_file}")"
victoria_metrics_version="$(yq -er '.spec.chart.spec.version' "${victoria_metrics_release_file}")"
victoria_metrics_repository_file="${repository_dir}/platform/sources/${victoria_metrics_source}/helm-repository.yaml"
victoria_metrics_repository="$(yq -er '.spec.url' "${victoria_metrics_repository_file}")"

echo "Installing ${victoria_metrics_chart} ${victoria_metrics_version} CRDs..."
helm show crds "${victoria_metrics_chart}" \
  --repo "${victoria_metrics_repository}" \
  --version "${victoria_metrics_version}" |
  kubectl --context "${cluster}" apply --filename -

echo "Installing Flux and its cluster entry point..."
kubectl --context "${cluster}" apply \
  --field-manager=kubelab-bootstrap \
  --force-conflicts \
  --server-side \
  --kustomize "${cluster_dir}/flux-system"
kubectl --context "${cluster}" -n flux-system wait deployment --all \
  --for=condition=Available \
  --timeout=5m

flux --context "${cluster}" reconcile source git flux-system
kubectl --context "${cluster}" -n flux-system annotate kustomization flux-system \
  reconcile.fluxcd.io/requestedAt="$(date -u +%s)" \
  --overwrite >/dev/null

for dependency in crds platform apps; do
  echo "Waiting for Flux Kustomization '${dependency}'..."
  for ((attempt = 1; attempt <= 150; attempt++)); do
    if kubectl --context "${cluster}" -n flux-system get kustomization "${dependency}" >/dev/null 2>&1; then
      break
    fi
    sleep 2
  done
  if ! kubectl --context "${cluster}" -n flux-system get kustomization "${dependency}" >/dev/null 2>&1; then
    echo "error: Flux Kustomization '${dependency}' was not created." >&2
    exit 1
  fi
  flux --context "${cluster}" reconcile kustomization "${dependency}"
done

flux --context "${cluster}" reconcile kustomization flux-system
flux --context "${cluster}" get kustomizations
flux --context "${cluster}" get helmreleases --all-namespaces

echo "Cluster '${cluster}' is bootstrapped and reconciled."
