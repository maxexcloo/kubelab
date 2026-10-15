#!/usr/bin/env bash
set -euo pipefail
umask 007
# This component backs up the single application database. Cluster declarations
# recreate roles and credentials; no role passwords are exported. Before restoring,
# bootstrap an empty Cluster with the same image and install the extensions listed
# in extensions.txt as an administrator (including Immich's vector/vchord).
# With owner credentials: bash /scripts/postgres_backup.sh restore /backups/postgres/<time>.
if [[ "${1:-backup}" == restore ]]; then
  archive_directory="${2:?Supply the completed backup directory}"
  (
    cd -- "$archive_directory"
    sha256sum --check SHA256SUMS
    # Extension comments belong to their administrator; the app owner cannot change them.
    pg_restore --dbname "$PGDATABASE" --exit-on-error --no-acl --no-comments --no-owner --single-transaction database.dump
  )
  exit
fi
if [[ "${1:-backup}" != backup ]]; then
  printf 'Usage: postgres_backup.sh [backup | restore DIRECTORY]\n' >&2
  exit 2
fi
backup_directory="${BACKUP_DIRECTORY:-/backups/postgres}"
timestamp="$(date -u +%Y-%m-%dT%H-%M-%SZ)"
mkdir -p -- "$backup_directory"
# Incomplete runs remain hidden and never replace an earlier completed backup.
staging_directory="$(mktemp -d "$backup_directory/.incomplete-${timestamp}-XXXXXX")"
chmod 0770 "$staging_directory"
pg_dump --file "$staging_directory/database.dump" --format custom --lock-wait-timeout 60s --no-password
pg_restore --list "$staging_directory/database.dump" > "$staging_directory/contents.txt"
psql --command 'SELECT e.extname, e.extversion, n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid = e.extnamespace ORDER BY e.extname' --csv --no-password --no-psqlrc > "$staging_directory/extensions.txt"
{
  printf 'Database: %s\nStarted: %s\n' "$PGDATABASE" "$timestamp"
  pg_dump --version
} > "$staging_directory/metadata.txt"
(
  cd -- "$staging_directory"
  sha256sum database.dump > SHA256SUMS
)
completed_directory="$backup_directory/$timestamp"
test ! -e "$completed_directory"
mv -- "$staging_directory" "$completed_directory"
printf 'Completed PostgreSQL backup: %s\n' "$timestamp"
