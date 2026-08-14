#!/usr/bin/env bash

set -euo pipefail

stacks=(bootstrap hsp truenas)
planned=0

for stack in "${stacks[@]}"; do
  stack_directory="tofu/${stack}"
  if [[ ! -d "${stack_directory}" ]]; then
    continue
  fi

  tofu -chdir="${stack_directory}" init -input=false
  tofu -chdir="${stack_directory}" plan -input=false -out=tfplan
  tofu -chdir="${stack_directory}" show -no-color tfplan >tfplan.txt
  planned=1
done

if [[ "${planned}" -eq 0 ]]; then
  echo "No OpenTofu stacks exist yet."
fi
