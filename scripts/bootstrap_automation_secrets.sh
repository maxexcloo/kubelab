#!/usr/bin/env bash
set -euo pipefail
umask 077

if [[ $# -ne 1 ]]; then
  echo "Usage: mise run bootstrap-automation-secrets <cluster>" >&2
  exit 1
fi

cluster="$1"
repository_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ ! -d "${repository_dir}/clusters/${cluster}" ]]; then
  echo "error: cluster '${cluster}' is not defined under clusters/." >&2
  exit 1
fi

configured=false
if [[ -f "${repository_dir}/clusters/${cluster}/b2-automation.yaml" ]]; then
  configured=true
  b2_authorisation="$(
    env -u OP_CONNECT_HOST -u OP_CONNECT_TOKEN \
      op item get --vault Homelab "B2 Automation: ${cluster}" --format json |
      jq -ejr '
        [
          (first(.fields[] | select(.id == "username")) | .value // empty),
          (first(.fields[] | select(.id == "password" or .id == "credential")) | .value // empty)
        ] as $credentials |
        if all($credentials[]; length > 0)
        then "Basic " + ($credentials | join(":") | @base64)
        else error("B2 automation credentials are incomplete")
        end
      '
  )"

  kubectl --context "${cluster}" create namespace crossplane-system --dry-run=client -o yaml |
    kubectl --context "${cluster}" apply -f -

  printf '%s' "${b2_authorisation}" |
    kubectl --context "${cluster}" -n crossplane-system create secret generic b2-credentials \
      --from-file=authorization=/dev/stdin \
      --dry-run=client -o yaml |
    kubectl --context "${cluster}" apply -f -
fi

if [[ -f "${repository_dir}/clusters/${cluster}/cloudflare-automation.yaml" ]]; then
  configured=true
  cloudflare_token="$(
    env -u OP_CONNECT_HOST -u OP_CONNECT_TOKEN \
      op item get --vault Homelab "Cloudflare App Policy: ${cluster}" --format json |
      jq -ejr 'first(.fields[] | select(.id == "password" or .id == "credential")) | .value // empty'
  )"
  redlib_monitoring_token="$(
    env -u OP_CONNECT_HOST -u OP_CONNECT_TOKEN \
      op item get --vault "Cluster: syd" Redlib --format json |
      jq -ejr '
        first(
          .fields[] |
          select(
            .id == "monitoring-token" or
            .id == "monitoring_token" or
            .label == "monitoring-token" or
            .label == "monitoring_token_rw"
          )
        ) |
        .value // empty
      '
  )"

  kubectl --context "${cluster}" create namespace crossplane-system --dry-run=client -o yaml |
    kubectl --context "${cluster}" apply -f -

  printf 'Bearer %s' "${cloudflare_token}" |
    kubectl --context "${cluster}" -n crossplane-system create secret generic cloudflare-app-policy-credentials \
      --from-file=authorization=/dev/stdin \
      --dry-run=client -o yaml |
    kubectl --context "${cluster}" apply -f -

  printf '%s' "${redlib_monitoring_token}" |
    kubectl --context "${cluster}" -n crossplane-system create secret generic redlib-waf-credentials \
      --from-file=monitoring-token=/dev/stdin \
      --dry-run=client -o yaml |
    kubectl --context "${cluster}" apply -f -
fi

if [[ "${configured}" != true ]]; then
  echo "error: cluster '${cluster}' has no staged external automation." >&2
  exit 1
fi
