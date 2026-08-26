#!/usr/bin/env bash
set -euo pipefail

temporary_directory="$(mktemp -d "${TMPDIR:-/tmp}/kubelab-manifests.XXXXXX")"

cleanup() {
  rm -rf -- "${temporary_directory:?}"
}

trap cleanup EXIT

manifest_directory="${temporary_directory}/manifests"
schema_directory="${temporary_directory}/schemas"
target_file="${temporary_directory}/targets"
mkdir -p "${manifest_directory}" "${schema_directory}"

kubeconform_flags=(
  -kubernetes-version 1.36.3
  -skip "ClusterProviderConfig,CustomResourceDefinition"
  -strict
  -summary
  -schema-location default
  -schema-location "${schema_directory}/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json"
  -schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/7b1e26ef9deea49293714d204c1a2270aab1178f/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json'
)

{
  find clusters -mindepth 1 -maxdepth 1 -type d
  yq eval-all -N -r 'select(.apiVersion == "kustomize.toolkit.fluxcd.io/v1" and .kind == "Kustomization") | .spec.path' clusters/*/*.yaml
} | sort -u >"${target_file}"

manifest_index=0
while IFS= read -r target; do
  target="${target#./}"
  kustomize build "${target}" >"${manifest_directory}/${manifest_index}.yaml"
  manifest_index=$((manifest_index + 1))
done <"${target_file}"

while IFS=$'\t' read -r xrd_group xrd_kind xrd_version; do
  mkdir -p "${schema_directory}/${xrd_group}"
  # shellcheck disable=SC2016
  KUBELAB_XRD_GROUP="${xrd_group}" \
    KUBELAB_XRD_KIND="${xrd_kind}" \
    KUBELAB_XRD_VERSION="${xrd_version}" \
    yq eval-all -o=json -I=2 '
      select(
        .apiVersion == "apiextensions.crossplane.io/v2" and
        .kind == "CompositeResourceDefinition" and
        .spec.group == strenv(KUBELAB_XRD_GROUP) and
        .spec.names.kind == strenv(KUBELAB_XRD_KIND)
      ) |
      .spec.versions[] |
      select(.name == strenv(KUBELAB_XRD_VERSION)) |
      .schema.openAPIV3Schema |
      .properties = ((.properties // {}) + {
        "apiVersion": {
          "enum": [strenv(KUBELAB_XRD_GROUP) + "/" + strenv(KUBELAB_XRD_VERSION)],
          "type": "string"
        },
        "kind": {
          "enum": [strenv(KUBELAB_XRD_KIND)],
          "type": "string"
        },
        "metadata": {
          "type": "object"
        }
      }) |
      .required = (((.required // []) + ["apiVersion", "kind", "metadata"]) | unique) |
      .additionalProperties = false |
      ."$schema" = "https://json-schema.org/draft/2020-12/schema"
    ' "${manifest_directory}"/*.yaml >"${schema_directory}/${xrd_group}/${xrd_kind}_${xrd_version}.json"
done < <(
  # shellcheck disable=SC2016
  yq eval-all -N -r '
    select(.apiVersion == "apiextensions.crossplane.io/v2" and .kind == "CompositeResourceDefinition") |
    .spec.group as $group |
    .spec.names.kind as $kind |
    .spec.versions[] |
    select(.served == true) |
    [$group, $kind, .name] |
    @tsv
  ' "${manifest_directory}"/*.yaml | sort -u
)

while IFS= read -r manifest; do
  kubeconform "${kubeconform_flags[@]}" "${manifest}"
done < <(
  {
    find "${manifest_directory}" -type f -name '*.yaml'
  } | sort -u
)
