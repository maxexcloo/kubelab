#!/bin/sh
set -eu

until pg_isready -h "$PGHOST" -U postgres -q; do
  echo "Waiting for $PGHOST"
  sleep 2
done
