#!/bin/sh
set -eu
# Called by backup.sh while LibreChat is stopped; uploads follow this dump.
# Keep the password out of command arguments and remove its temporary file.
umask 077
{
  printf 'password: |-\n'
  printf '%s\n' "$MONGODB_ROOT_PASSWORD" | sed 's/^/  /'
} > /tmp/mongodump.yaml
timeout 600 mongodump --config=/tmp/mongodump.yaml \
  --archive=/snapshot/mongodb.archive --authenticationDatabase=admin \
  --db=LibreChat --gzip --host=mongodb --port=27017 --username=root || {
  rm -f /tmp/mongodump.yaml
  exit 1
}
rm -f /tmp/mongodump.yaml
