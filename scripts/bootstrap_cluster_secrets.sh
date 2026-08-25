#!/usr/bin/env bash
set -euo pipefail
umask 077

if [[ $# -ne 0 ]]; then
  echo "Usage: mise run bootstrap-secrets" >&2
  exit 1
fi

cluster="$(kubectl config current-context)"
repository_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ ! -d "${repository_dir}/clusters/${cluster}" ]]; then
  echo "error: cluster '${cluster}' is not defined under clusters/." >&2
  exit 1
fi

credentials_file="$(mktemp)"
trap 'rm -f -- "${credentials_file}"' EXIT

env -u OP_CONNECT_HOST -u OP_CONNECT_TOKEN \
  op document get --vault Homelab "Connect Credentials: ${cluster}" --out-file "${credentials_file}" --force >/dev/null
jq -e 'type == "object"' "${credentials_file}" >/dev/null

kubectl --context "${cluster}" create namespace external-secrets --dry-run=client -o yaml |
  kubectl --context "${cluster}" apply -f -

env -u OP_CONNECT_HOST -u OP_CONNECT_TOKEN \
  op item get --vault Homelab "Connect Token: ${cluster}" --format json |
  jq -ejr 'first(.fields[] | select(.id == "credential")) | .value // empty' |
  kubectl --context "${cluster}" -n external-secrets create secret generic onepassword-connect \
    --from-file=1password-credentials.json="${credentials_file}" \
    --from-file=token=/dev/stdin \
    --dry-run=client -o yaml |
  kubectl --context "${cluster}" apply -f -
