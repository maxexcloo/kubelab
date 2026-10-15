#!/usr/bin/env bash
set -euo pipefail

cluster="${1:?Usage: backup_app.sh <cluster> <application>}"
application="${2:?Usage: backup_app.sh <cluster> <application>}"
timestamp="$(date -u +%s)"
found=false

while IFS= read -r cron_job; do
  case "$cron_job" in
    file-backup | postgres-backup)
      found=true
      kubectl --context "$cluster" create job \
        --from "cronjob/$cron_job" \
        --namespace "$application" \
        "$cron_job-manual-$timestamp"
      ;;
  esac
done < <(kubectl --context "$cluster" get cronjobs --namespace "$application" --output 'jsonpath={range .items[*]}{.metadata.name}{"\n"}{end}')

if [[ "$found" == false ]]; then
  printf 'No configured backup jobs found for %s.\n' "$application" >&2
  exit 1
fi
