#!/usr/bin/env bash
set -euo pipefail

manifest_directory="${1:?Usage: check_manifests.sh <manifest-directory>}"
cache_directory="${HOME}/.cache/kubelab/kubeconform"
# Keep validation aligned with the deployed cluster API.
kubernetes_version="$(kubectl version --client -o json | yq -r '.clientVersion.gitVersion')"
# renovate: datasource=git-refs depName=https://github.com/datreeio/CRDs-catalog
crd_catalog_revision="27233a506de0085e71c7f9702597806a7f95eb24"
mkdir -p "${cache_directory}"

# Kinds without a published schema, including Kubelab's own composite resources, are not validated.
kubeconform \
  -cache "${cache_directory}" \
  -ignore-missing-schemas \
  -kubernetes-version "${kubernetes_version#v}" \
  -schema-location default \
  -schema-location "https://raw.githubusercontent.com/datreeio/CRDs-catalog/${crd_catalog_revision}/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json" \
  -skip ClusterProviderConfig,CustomResourceDefinition \
  -strict \
  -summary \
  "${manifest_directory}"
