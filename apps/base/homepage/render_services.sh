#!/bin/sh
set -eu

# Render only non-secret Homelab endpoint references; Homepage owns widget secrets.
template=${1:?Usage: render_services.sh template output homelab-directory}
output=${2:?Usage: render_services.sh template output homelab-directory}
homelab_directory=${3:?Usage: render_services.sh template output homelab-directory}
: "${HOMELAB_INFRASTRUCTURE_FILE:?HOMELAB_INFRASTRUCTURE_FILE is required}"
temporary_directory=$(mktemp -d)
trap 'rm -fr "$temporary_directory"' EXIT

script_directory=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
services="$template"
if [ "$(yq 'tag' "$template")" = '!!seq' ]; then
  : "${HOMEPAGE_BESZEL_URL:?HOMEPAGE_BESZEL_URL is required}"
  TEMPLATE="$template" INFRASTRUCTURE="$HOMELAB_INFRASTRUCTURE_FILE" \
    PROVIDERS="$homelab_directory/data/providers.yaml" \
    yq --from-file "$script_directory/machine_widgets.yq" \
    "$homelab_directory/data/machines.yaml" > "$temporary_directory/machines.yaml"
  services="$temporary_directory/machines.yaml"
fi
# Resolve inventory references in one pass, including nested widget URLs.
printf '{}\n' > "$temporary_directory/dns.json"
if yq -e '.. | select(tag == "!!str" and test("^homelab-dns://"))' \
  "$services" >/dev/null 2>&1; then
  # shellcheck disable=SC2016
  yq ea -o=json '
    [. as $zone | .records[] |
      select(.type == "CNAME" and .name != "@" and (.name | contains("*") | not)) |
      {"target": .content, "hostname": (.name + "." + $zone.name)}] |
    .[] as $record ireduce ({}; .[$record.target] += [$record.hostname])
  ' "$homelab_directory"/data/dns/*.yaml > "$temporary_directory/dns.json"
fi
MACHINES="$homelab_directory/data/machines.yaml" DOMAINS="$homelab_directory/data/domains.yaml" \
  INFRASTRUCTURE="$HOMELAB_INFRASTRUCTURE_FILE" \
  DNS="$temporary_directory/dns.json" \
  yq --from-file "$script_directory/resolve_endpoints.yq" \
  "$services" > "$temporary_directory/services.yaml"

# Providers are service cards with Gatus widgets, rendered by render_dashboard.sh.
yq -e '.providers | length > 0' "$homelab_directory/data/providers.yaml" >/dev/null
printf '[]\n' > "$temporary_directory/bookmarks.yaml"

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
