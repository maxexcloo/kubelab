#!/bin/sh
set -eu

# Render only non-secret Homelab endpoint references; Homepage owns widget secrets.
template=${1:?Usage: render_services.sh template output homelab-directory}
output=${2:?Usage: render_services.sh template output homelab-directory}
homelab_directory=${3:?Usage: render_services.sh template output homelab-directory}
temporary_directory=$(mktemp -d)
trap 'rm -fr "$temporary_directory"' EXIT

script_directory=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
printf '{}\n' > "$temporary_directory/infrastructure.json"
cp "$template" "$temporary_directory/services.yaml"
if [ "$(yq 'tag' "$template")" = '!!seq' ]; then
  TEMPLATE="$template" INFRASTRUCTURE="${HOMELAB_INFRASTRUCTURE_FILE:-$temporary_directory/infrastructure.json}" \
    PROVIDERS="$homelab_directory/data/providers.yaml" \
    HOMEPAGE_BESZEL_URL="${HOMEPAGE_BESZEL_URL:-}" \
    yq --from-file "$script_directory/machine_widgets.yq" \
    "$homelab_directory/data/machines.yaml" > "$temporary_directory/services.yaml"
fi
# Resolve inventory references in one pass, including nested widget URLs.
printf '{}\n' > "$temporary_directory/dns.json"
if yq -e '.. | select(tag == "!!str" and test("^homelab-dns://"))' \
  "$temporary_directory/services.yaml" >/dev/null 2>&1; then
  # shellcheck disable=SC2016
  yq ea -o=json '
    [. as $zone | .records[] |
      select(.type == "CNAME" and .name != "@" and (.name | contains("*") | not)) |
      {"target": .content, "hostname": (.name + "." + $zone.name)}] |
    .[] as $record ireduce ({}; .[$record.target] += [$record.hostname])
  ' "$homelab_directory"/data/dns/*.yaml > "$temporary_directory/dns.json"
fi
MACHINES="$homelab_directory/data/machines.yaml" DOMAINS="$homelab_directory/data/domains.yaml" \
  INFRASTRUCTURE="${HOMELAB_INFRASTRUCTURE_FILE:-$temporary_directory/infrastructure.json}" \
  DNS="$temporary_directory/dns.json" \
  yq --from-file "$script_directory/resolve_endpoints.yq" \
  "$temporary_directory/services.yaml" > "$temporary_directory/resolved.yaml"
mv "$temporary_directory/resolved.yaml" "$temporary_directory/services.yaml"

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
