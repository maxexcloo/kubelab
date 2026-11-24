#!/bin/sh
set -eu

description=Homepage
encoded_credentials=$(printf '%s:%s' "$ADMIN_USERNAME" "$ADMIN_PASSWORD" | base64)
authorization=$(printf '%s' "$encoded_credentials" | tr -d '\n')

miniflux_api_keys() {
  printf 'header = "Authorization: Basic %s"\n' "$authorization" |
    curl --config - --fail --silent --show-error --max-time 15 \
      "$@" http://miniflux:8080/v1/api-keys
}

keys=$(miniflux_api_keys)
token=$(printf '%s' "$keys" | jq -er --arg description "$description" '
  [.[] | select(.description == $description)] |
  if length > 1 then error("Multiple Miniflux keys are named Homepage")
  elif length == 1 then .[0].token | select(type == "string" and length > 0)
  else "" end
')
if [ -z "$token" ]; then
  body=$(jq -cn --arg description "$description" '{description: $description}')
  key=$(miniflux_api_keys --json "$body")
  token=$(printf '%s' "$key" | jq -er '.token | select(type == "string" and length > 0)')
fi

patch=$(printf '%s' "$token" | jq -Rs '{stringData: {token: .}}')
printf '%s' "$patch" |
  kubectl --namespace "$POD_NAMESPACE" patch secret miniflux-homepage-key --type merge --patch-file /dev/stdin
