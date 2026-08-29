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
schema_cache_directory=".cache/kubeconform"
remote_schema_cache_directory="${schema_cache_directory}/remote"
kubernetes_version="1.36.3"
crd_catalog_revision="7b1e26ef9deea49293714d204c1a2270aab1178f"
mkdir -p \
  "${manifest_directory}" \
  "${remote_schema_cache_directory}" \
  "${schema_directory}"

provider_http_version="$(
  yq -r '.spec.values.provider.packages[] | select(contains("provider-http:")) | split(":")[-1]' \
    platform/automation/crossplane/helm-release.yaml
)"
provider_http_schema_root="${schema_cache_directory}/provider-http-${provider_http_version}"
provider_http_schema_directory="${provider_http_schema_root}/http.m.crossplane.io"
provider_http_schema_file="${provider_http_schema_directory}/request_v1alpha2.json"
resolved_schema_directory="${schema_cache_directory}/resolved"
mkdir -p "${provider_http_schema_directory}"
if [[ ! -s "${provider_http_schema_file}" ]]; then
  provider_http_schema_temporary_file="${provider_http_schema_file}.tmp"
  # shellcheck disable=SC2016
  curl \
    --fail \
    --location \
    --silent \
    --show-error \
    "https://raw.githubusercontent.com/crossplane-contrib/provider-http/${provider_http_version}/package/crds/http.m.crossplane.io_requests.yaml" |
    yq -o=json -I=2 '
      .spec.versions[] |
      select(.name == "v1alpha2") |
      .schema.openAPIV3Schema |
      ."$schema" = "https://json-schema.org/draft/2020-12/schema"
    ' >"${provider_http_schema_temporary_file}"
  mv "${provider_http_schema_temporary_file}" "${provider_http_schema_file}"
fi

materialise_cached_schemas() {
  while IFS=$'\t' read -r api_version kind; do
    group=""
    version="${api_version}"
    if [[ "${api_version}" == */* ]]; then
      group="${api_version%/*}"
      version="${api_version##*/}"
    fi
    kind_suffix="-${version}"
    if [[ -n "${group}" ]]; then
      kind_suffix="-${group%%.*}-${version}"
    fi
    default_url="https://raw.githubusercontent.com/yannh/kubernetes-json-schema/master/v${kubernetes_version}-standalone-strict/${kind}${kind_suffix}.json"
    catalog_url="https://raw.githubusercontent.com/datreeio/CRDs-catalog/${crd_catalog_revision}/${group}/${kind}_${version}.json"
    for url in "${default_url}" "${catalog_url}"; do
      cache_key="$(printf '%s' "${url}" | shasum -a 256 | cut -d' ' -f1)"
      if [[ -s "${remote_schema_cache_directory}/${cache_key}" ]]; then
        mkdir -p "${resolved_schema_directory}/${group}"
        cp \
          "${remote_schema_cache_directory}/${cache_key}" \
          "${resolved_schema_directory}/${group}/${kind}_${version}.json"
        break
      fi
    done
  done < <(
    yq eval -N -r '
      select(.apiVersion != null and .kind != null) |
      [.apiVersion, (.kind | downcase)] |
      @tsv
    ' "${manifest_directory}"/*.yaml | sort -u
  )
}

kubeconform_flags=(
  -kubernetes-version "${kubernetes_version}"
  -skip "ClusterProviderConfig,CustomResourceDefinition"
  -strict
  -summary
  -cache "${remote_schema_cache_directory}"
  -schema-location "${resolved_schema_directory}/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json"
  -schema-location "${schema_directory}/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json"
  -schema-location "${provider_http_schema_root}/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json"
  -schema-location default
  -schema-location "https://raw.githubusercontent.com/datreeio/CRDs-catalog/${crd_catalog_revision}/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json"
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
  xrd_resource_kind="$(printf '%s' "${xrd_kind}" | tr '[:upper:]' '[:lower:]')"
  # shellcheck disable=SC2016
  KUBELAB_XRD_GROUP="${xrd_group}" \
    KUBELAB_XRD_KIND="${xrd_kind}" \
    KUBELAB_XRD_VERSION="${xrd_version}" \
    yq eval -o=json -I=2 '
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
    ' "${manifest_directory}"/*.yaml >"${schema_directory}/${xrd_group}/${xrd_resource_kind}_${xrd_version}.json"
done < <(
  # shellcheck disable=SC2016
  yq eval -N -r '
    select(.apiVersion == "apiextensions.crossplane.io/v2" and .kind == "CompositeResourceDefinition") |
    .spec.group as $group |
    .spec.names.kind as $kind |
    .spec.versions[] |
    select(.served == true) |
    [$group, $kind, .name] |
    @tsv
  ' "${manifest_directory}"/*.yaml | sort -u
)

materialise_cached_schemas
kubeconform "${kubeconform_flags[@]}" "${manifest_directory}"
materialise_cached_schemas
