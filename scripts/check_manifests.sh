#!/usr/bin/env bash
set -euo pipefail

kubeconform_flags=(
  -kubernetes-version 1.36.3
  -skip CustomResourceDefinition
  -strict
  -summary
  -schema-location default
  -schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/7b1e26ef9deea49293714d204c1a2270aab1178f/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json'
)

while IFS= read -r target; do
  target="${target#./}"
  kustomize build "${target}" | kubeconform "${kubeconform_flags[@]}"
done < <(
  {
    find clusters -mindepth 1 -maxdepth 1 -type d
    yq eval-all -N -r 'select(.apiVersion == "kustomize.toolkit.fluxcd.io/v1" and .kind == "Kustomization") | .spec.path' clusters/*/*.yaml
  } | sort -u
)
