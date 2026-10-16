#!/bin/sh
set -eu

# Generate updates GUI authentication without replacing devices, folders or keys.
# Read the password from standard input so it never enters process arguments.
syncthing generate --gui-password=- --gui-user="$(cat /credentials/username)" </credentials/password
