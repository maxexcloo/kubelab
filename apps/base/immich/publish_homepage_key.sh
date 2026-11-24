#!/bin/sh
set -eu

base=http://immich-server:2283/api
name='Kubelab Homepage'
permission=server.statistics

immich() {
  curl --silent --show-error --max-time 15 "$@"
}

scoped_key() {
  [ -n "$1" ] || return 1
  status=$(printf 'header = "x-api-key: %s"\n' "$1" |
    immich --config - --output /tmp/key.json --write-out '%{http_code}' "$base/api-keys/me") || exit 1
  case "$status" in
    200)
      permissions=$(jq -ec '.permissions | arrays' /tmp/key.json) || exit 1
      [ "$permissions" = "[\"$permission\"]" ]
      ;;
    401 | 403) return 1 ;;
    *) printf 'Immich key check returned HTTP %s\n' "$status" >&2; exit 1 ;;
  esac
}

session_request() {
  printf 'header = "Authorization: Bearer %s"\n' "$session" | immich --config - --fail "$@"
}

kube() {
  kubectl --kubeconfig /dev/null --cache-dir /tmp/kubectl "$@"
}

staged_secret=$(kube get secret immich-homepage-key -o json)
staged_token=$(printf '%s' "$staged_secret" | jq -r '.data.token // "" | @base64d')
if scoped_key "$staged_token"; then
  exit 0
fi

if scoped_key "${HOMEPAGE_TOKEN-}"; then
  token=$HOMEPAGE_TOKEN
else
  login=$(jq -cn '{email: env.IMMICH_USERNAME, password: env.IMMICH_PASSWORD}' |
    immich --fail --json @- "$base/auth/login")
  session=$(printf '%s' "$login" | jq -er '.accessToken | select(type == "string" and length > 0)')
  trap 'session_request --request POST "$base/auth/logout" >/dev/null' EXIT
  printf '%s' "$login" | jq -e '.isAdmin == true' >/dev/null

  keys=$(session_request "$base/api-keys")
  key_id=$(printf '%s' "$keys" | jq -er --arg name "$name" --arg permission "$permission" '
    [.[] | select(.name == $name)] |
    if length > 1 then error("Multiple managed Immich Homepage keys")
    elif length == 1 then
      .[0] | if .permissions == [$permission] then .id else error("Unexpected Immich Homepage key permissions") end
    else "" end
  ')
  if [ -n "$key_id" ]; then
    # Immich only returns the secret when it issues or rotates the key.
    key=$(session_request --request POST "$base/api-keys/$key_id/rotate")
  else
    body=$(jq -cn --arg name "$name" --arg permission "$permission" '{name: $name, permissions: [$permission]}')
    key=$(session_request --json "$body" "$base/api-keys")
  fi
  token=$(printf '%s' "$key" | jq -er '.secret | select(type == "string" and length > 0)')
fi

printf 'header = "x-api-key: %s"\n' "$token" |
  immich --config - --fail --output /dev/null "$base/server/statistics"
patch=$(printf '%s' "$token" | jq -Rs '{stringData: {token: .}}')
printf '%s' "$patch" |
  kube patch secret immich-homepage-key --type merge --patch-file /dev/stdin
