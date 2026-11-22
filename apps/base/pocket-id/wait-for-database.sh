#!/bin/sh
set -eu

until pg_isready -h pocket-id-database-rw -U postgres -q; do
  echo waiting for pocket-id-database-rw
  sleep 2
done
