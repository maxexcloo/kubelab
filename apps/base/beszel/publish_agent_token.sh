#!/bin/sh
set -eu

login_body=$(jq -cn '{identity: env.USER_EMAIL, password: env.USER_PASSWORD}')
login=$(printf '%s' "$login_body" |
  curl --fail --silent --show-error --max-time 15 --json @- \
    http://beszel:8090/api/collections/users/auth-with-password)
session=$(printf '%s' "$login" | jq -er '.token | select(type == "string" and length > 0)')

universal_token() {
  printf 'header = "Authorization: Bearer %s"\n' "$session" |
    curl --config - --fail --silent --show-error --max-time 15 --json "$1" \
      http://beszel:8090/api/beszel/universal-token
}

state=$(universal_token '{}')
token=$(printf '%s' "$state" | jq -er '
  if .active == true and .permanent == true then .token | select(type == "string" and length > 0)
  elif .active == false and .permanent == false then ""
  else error("The Beszel universal token is not permanent") end
')
if [ -z "$token" ]; then
  state=$(universal_token '{"enable":1,"permanent":1}')
  token=$(printf '%s' "$state" | jq -er 'select(.active == true and .permanent == true) | .token | select(type == "string" and length > 0)')
fi

patch=$(printf '%s' "$token" | jq -Rs '{stringData: {token: .}}')
printf '%s' "$patch" |
  kubectl --kubeconfig /dev/null --cache-dir /tmp/beszel-agent-token --namespace "$POD_NAMESPACE" \
    patch secret beszel-agent-token --type merge --patch-file /dev/stdin
