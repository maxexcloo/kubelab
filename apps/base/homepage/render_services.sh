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
  mkdir -p "$homelab_directory"
  wget -q -T 30 -O "$temporary_directory/homelab.tar.gz" \
    https://codeload.github.com/maxexcloo/homelab/tar.gz/refs/heads/main
  tar -xzf "$temporary_directory/homelab.tar.gz" -C "$homelab_directory" --strip-components=1
fi

domain=$(yq -e -r '.domains.infrastructure' "$homelab_directory/data/domains.yaml")
cp "$template" "$temporary_directory/services.yaml"
if [ "$(yq 'tag' "$template")" = '!!seq' ]; then
  printf '{}\n' > "$temporary_directory/infrastructure.json"
  TEMPLATE="$template" INFRASTRUCTURE="${HOMELAB_INFRASTRUCTURE_FILE:-$temporary_directory/infrastructure.json}" \
    HOMEPAGE_BESZEL_URL="${HOMEPAGE_BESZEL_URL:-}" \
    yq --from-file "$(dirname "$0")/machine_widgets.yq" \
    "$homelab_directory/data/machines.yaml" > "$temporary_directory/services.yaml"
fi
# Resolve public service names from Homelab's authoritative DNS declarations.
yq -r '.. | select(tag == "!!str") | select(test("^homelab-dns://"))' \
  "$temporary_directory/services.yaml" | sort -u > "$temporary_directory/dns-references"
while IFS= read -r reference; do
  target=${reference#homelab-dns://}
  # shellcheck disable=SC2016
  TARGET="$target" yq ea -N -r '
    [. as $zone | .records[] |
      select(.type == "CNAME" and .content == strenv(TARGET)) |
      select(.name != "@" and (.name | contains("*") | not)) |
      (.name + "." + $zone.name)] | unique |
    select(length == 1) | .[0]
  ' "$homelab_directory"/data/dns/*.yaml > "$temporary_directory/hostname"
  hostname=$(cat "$temporary_directory/hostname")
  [ -n "$hostname" ] || { echo "Missing or ambiguous DNS reference: $reference" >&2; exit 1; }
  REFERENCE="$reference" ENDPOINT="https://$hostname" yq \
    '(.. | select(tag == "!!str" and . == strenv(REFERENCE))) = strenv(ENDPOINT)' \
    "$temporary_directory/services.yaml" > "$temporary_directory/next.yaml"
  mv "$temporary_directory/next.yaml" "$temporary_directory/services.yaml"
done < "$temporary_directory/dns-references"

yq -r '.. | select(tag == "!!str") | select(test("^homelab://"))' \
  "$temporary_directory/services.yaml" > "$temporary_directory/references-unsorted"
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
    'explode(.) | .machines[strenv(NETWORK)][strenv(MACHINE)]' \
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
  if [ "$(yq '.tailscale.enabled' "$temporary_directory/machine.yaml")" = false ]; then
    authority=$(yq -e -r '.interfaces[0].address // .private_ipv4' "$temporary_directory/machine.yaml")
  fi
  case "$scheme:$port" in http:80 | https:443) ;; *) authority="$authority:$port" ;; esac
  REFERENCE="$reference" ENDPOINT="$scheme://$authority$suffix" yq \
    '(.. | select(tag == "!!str" and . == strenv(REFERENCE))) = strenv(ENDPOINT)' \
    "$temporary_directory/services.yaml" > "$temporary_directory/next.yaml"
  mv "$temporary_directory/next.yaml" "$temporary_directory/services.yaml"
done < "$temporary_directory/references"

# Keep Homepage's provider bookmarks in the shared Homelab inventory.
yq -e '.providers | length > 0' "$homelab_directory/data/providers.yaml" >/dev/null
yq '.providers | to_entries | map({(.key): [{"description": .value.description, "href": .value.url, "icon": .value.icon}]}) | [{"Providers": .}]' \
  "$homelab_directory/data/providers.yaml" > "$temporary_directory/bookmarks.yaml"

# Rename on the destination filesystem so readers never see a partial update.
mkdir -p "$(dirname "$output")"
for file in services bookmarks; do
  destination="$output"
  if [ "$file" = bookmarks ]; then
    destination="$(dirname "$output")/bookmarks.yaml"
  fi
  if ! cmp -s "$temporary_directory/$file.yaml" "$destination"; then
    staged_output=$(mktemp "$destination.XXXXXX")
    cp "$temporary_directory/$file.yaml" "$staged_output"
    chmod 644 "$staged_output"
    mv "$staged_output" "$destination"
  fi
done
