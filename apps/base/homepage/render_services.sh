#!/bin/sh
set -eu

if [ "${1:-}" = --watch ]; then
  shift
  trap 'exit 0' INT TERM
  while true; do
    if ! sh "$0" "$@"; then
      echo 'Homelab endpoint refresh failed; retaining the last valid configuration' >&2
    fi
    sleep 300 &
    wait $!
  done
fi

# Render only non-secret Homelab endpoint references; Homepage owns widget secrets.
template=${1:?Usage: render_services.sh template output [homelab-directory]}
output=${2:?Usage: render_services.sh template output [homelab-directory]}
homelab_directory=${3:-}
temporary_directory=$(mktemp -d)
trap 'rm -rf "$temporary_directory"' EXIT

if [ -z "$homelab_directory" ]; then
  homelab_directory="$temporary_directory/homelab"
  mkdir -p "$homelab_directory/data"
  wget -q -T 30 -O "$temporary_directory/revision.json" \
    https://api.github.com/repos/maxexcloo/homelab/commits/main
  revision=$(yq -e -r '.sha' "$temporary_directory/revision.json")
  case "$revision" in
    *[!a-f0-9]* | '') echo 'Invalid Homelab revision' >&2; exit 1 ;;
  esac
  [ "${#revision}" -eq 40 ]
  for file in domains machines; do
    wget -q -T 30 -O "$homelab_directory/data/$file.yaml" \
      "https://raw.githubusercontent.com/maxexcloo/homelab/$revision/data/$file.yaml"
  done
fi

domain=$(yq -e -r '.domains.infrastructure' "$homelab_directory/data/domains.yaml")
cp "$template" "$temporary_directory/services.yaml"
yq -r '.. | select(tag == "!!str") | select(test("^homelab://"))' \
  "$template" > "$temporary_directory/references-unsorted"
sort -u "$temporary_directory/references-unsorted" > "$temporary_directory/references"

while IFS= read -r reference; do
  remainder=${reference#homelab://}
  network=${remainder%%/*}
  remainder=${remainder#*/}
  machine=${remainder%%/*}
  remainder=${remainder#*/}
  service=${remainder%%/*}
  suffix=${remainder#"$service"}
  case "$network/$machine/$service" in
    *[!a-z0-9/-]* | */ | /* | *//*) echo "Invalid endpoint reference: $reference" >&2; exit 1 ;;
  esac
  NETWORK="$network" MACHINE="$machine" yq -e \
    '.machines[strenv(NETWORK)][strenv(MACHINE)]' \
    "$homelab_directory/data/machines.yaml" > "$temporary_directory/machine.yaml"
  hostname=$(MACHINE="$machine" yq -r '.hostname // strenv(MACHINE)' "$temporary_directory/machine.yaml")
  if [ "$service" = management ]; then
    scheme=https
    port=$(yq -e -r '.management_port' "$temporary_directory/machine.yaml")
  else
    scheme=$(SERVICE="$service" yq -e -r '.services[strenv(SERVICE)].scheme' "$temporary_directory/machine.yaml")
    port=$(SERVICE="$service" yq -e -r '.services[strenv(SERVICE)].port' "$temporary_directory/machine.yaml")
  fi
  case "$scheme" in http | https) ;; *) echo "Invalid endpoint scheme: $reference" >&2; exit 1 ;; esac
  case "$port" in *[!0-9]* | '') echo "Invalid endpoint port: $reference" >&2; exit 1 ;; esac
  [ "$port" -ge 1 ] && [ "$port" -le 65535 ]
  authority="$hostname.$network.$domain"
  case "$scheme:$port" in http:80 | https:443) ;; *) authority="$authority:$port" ;; esac
  REFERENCE="$reference" ENDPOINT="$scheme://$authority$suffix" yq \
    '(.. | select(tag == "!!str" and . == strenv(REFERENCE))) = strenv(ENDPOINT)' \
    "$temporary_directory/services.yaml" > "$temporary_directory/next.yaml"
  mv "$temporary_directory/next.yaml" "$temporary_directory/services.yaml"
done < "$temporary_directory/references"

# Rename on the destination filesystem so readers never see a partial update.
mkdir -p "$(dirname "$output")"
if ! cmp -s "$temporary_directory/services.yaml" "$output"; then
  staged_output=$(mktemp "$output.XXXXXX")
  cp "$temporary_directory/services.yaml" "$staged_output"
  chmod 644 "$staged_output"
  mv "$staged_output" "$output"
fi
