#!/bin/sh
set -eu
: "${HOMELAB_CLUSTER:?HOMELAB_CLUSTER is required}"

if [ "${1:-}" = --watch ]; then
  shift
  trap 'exit 0' INT TERM
  while true; do
    if ! sh "$0" "$@"; then
      echo 'Homelab route refresh failed; retaining the last valid configuration' >&2
    fi
    sleep 300 &
    wait $!
  done
fi

output_directory=${1:?Usage: render_host_services.sh output-directory}
script_directory=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
temporary_directory=$(mktemp -d)
trap 'rm -fr "$temporary_directory"' EXIT
homelab_directory=${HOMELAB_DIRECTORY:-}
if [ -z "$homelab_directory" ]; then
  : "${HOMELAB_REPOSITORY:?HOMELAB_REPOSITORY is required}"
  : "${HOMELAB_BRANCH:?HOMELAB_BRANCH is required}"
  repository=${HOMELAB_REPOSITORY#https://github.com/}
  repository=${repository%.git}
  wget -O "$temporary_directory/repository.tar.gz" -q -T 30 \
    "https://codeload.github.com/$repository/tar.gz/refs/heads/$HOMELAB_BRANCH"
  homelab_directory="$temporary_directory/homelab"
  mkdir "$homelab_directory"
  tar -xzf "$temporary_directory/repository.tar.gz" -C "$homelab_directory" --strip-components=1
fi

HOMELAB_DOMAINS="$homelab_directory/data/domains.yaml" \
  yq --from-file "$script_directory/host_services.yq" \
  "$homelab_directory/data/machines.yaml" > "$temporary_directory/routes.yaml"
mkdir -p "$output_directory"
if ! cmp -s "$temporary_directory/routes.yaml" "$output_directory/homelab.yaml"; then
  staged_output=$(mktemp "$output_directory/.homelab.XXXXXX")
  cp "$temporary_directory/routes.yaml" "$staged_output"
  chmod 644 "$staged_output"
  mv "$staged_output" "$output_directory/homelab.yaml"
fi
