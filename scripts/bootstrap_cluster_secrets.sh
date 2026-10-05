#!/usr/bin/env bash
set -euo pipefail
umask 077

if [[ $# -ne 1 ]]; then
  echo "Usage: mise run bootstrap-secrets <cluster>" >&2
  exit 1
fi

cluster="$1"
repository_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ ! -d "${repository_dir}/clusters/${cluster}" ]]; then
  echo "error: cluster '${cluster}' is not defined under clusters/." >&2
  exit 1
fi

temporary_directory="$(mktemp -d)"
trap 'rm -rf -- "${temporary_directory:?}"' EXIT
credentials_file="${temporary_directory}/credentials.json"
token_file="${temporary_directory}/token"

env -u OP_CONNECT_HOST -u OP_CONNECT_TOKEN \
  op document get --vault Homelab "Connect Credentials: ${cluster}" --out-file "${credentials_file}" --force >/dev/null
jq -e 'type == "object"' "${credentials_file}" >/dev/null

env -u OP_CONNECT_HOST -u OP_CONNECT_TOKEN \
  op item get --vault Homelab "Connect Token: ${cluster}" --format json |
  jq -ejr 'first(.fields[] | select(.id == "credential")) | .value | select(type == "string" and length > 0)' >"${token_file}"

kubectl --context "${cluster}" create namespace external-secrets --dry-run=client -o yaml |
  kubectl --context "${cluster}" apply -f -

kubectl --context "${cluster}" -n external-secrets create secret generic onepassword-connect \
    --from-file=1password-credentials.json="${credentials_file}" \
    --from-file=token="${token_file}" \
    --dry-run=client -o yaml |
  kubectl --context "${cluster}" apply -f -
