#!/usr/bin/env bash
set -euo pipefail

temporary_directory="$(mktemp -d "${TMPDIR:-/tmp}/kubelab-manifests.XXXXXX")"

cleanup() {
  rm -fr -- "${temporary_directory:?}"
}

trap cleanup EXIT

manifest_directory="${1:?Usage: check_manifests.sh <manifest-directory>}"
schema_directory="${temporary_directory}/schemas"
schema_cache_directory=".cache/kubeconform"
remote_schema_cache_directory="${schema_cache_directory}/remote"
# Keep validation aligned with the deployed cluster API.
kubernetes_version="1.37.1"
crd_catalog_revision="fd90051867733c60d32d16450556e9cd18459aef"
mkdir -p \
  "${remote_schema_cache_directory}" \
  "${schema_directory}"

provider_http_version="$(
  yq -r '.spec.values.provider.packages[] | select(contains("provider-http:")) | split(":")[-1]' \
    platform/automation/crossplane/helm-release.yaml
)"
provider_http_schema_root="${schema_cache_directory}/provider-http-${provider_http_version}"
provider_http_schema_directory="${provider_http_schema_root}/http.m.crossplane.io"
provider_http_schema_file="${provider_http_schema_directory}/request_v1alpha2.json"
mkdir -p "${provider_http_schema_directory}"
if [[ ! -s "${provider_http_schema_file}" ]]; then
  provider_http_schema_temporary_file="${provider_http_schema_file}.tmp"
  # shellcheck disable=SC2016
  curl \
    --fail \
    --location \
    --show-error \
    --silent \
    "https://raw.githubusercontent.com/crossplane-contrib/provider-http/${provider_http_version}/package/crds/http.m.crossplane.io_requests.yaml" |
    yq -I=2 -o=json '
      .spec.versions[] |
      select(.name == "v1alpha2") |
      .schema.openAPIV3Schema |
      ."$schema" = "https://json-schema.org/draft/2020-12/schema"
    ' >"${provider_http_schema_temporary_file}"
  mv "${provider_http_schema_temporary_file}" "${provider_http_schema_file}"
fi

kubeconform_flags=(
  -cache "${remote_schema_cache_directory}"
  -kubernetes-version "${kubernetes_version}"
  -schema-location "${schema_directory}/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json"
  -schema-location "${provider_http_schema_root}/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json"
  -schema-location default
  -schema-location "https://raw.githubusercontent.com/datreeio/CRDs-catalog/${crd_catalog_revision}/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json"
  -skip "ClusterProviderConfig,CustomResourceDefinition"
  -strict
  -summary
)

manifest_files=()
while IFS= read -r manifest_file; do
  manifest_files+=("${manifest_file}")
done < <(find "${manifest_directory}" -type f -name '*.yaml' | sort)

while IFS=$'\t' read -r xrd_group xrd_kind xrd_version; do
  mkdir -p "${schema_directory}/${xrd_group}"
  xrd_resource_kind="$(printf '%s' "${xrd_kind}" | tr '[:upper:]' '[:lower:]')"
  # shellcheck disable=SC2016
  KUBELAB_XRD_GROUP="${xrd_group}" \
    KUBELAB_XRD_KIND="${xrd_kind}" \
    KUBELAB_XRD_VERSION="${xrd_version}" \
    yq eval-all -I=2 -o=json '
      [select(
        .apiVersion == "apiextensions.crossplane.io/v2" and
        .kind == "CompositeResourceDefinition" and
        .spec.group == strenv(KUBELAB_XRD_GROUP) and
        .spec.names.kind == strenv(KUBELAB_XRD_KIND)
      )] | .[0] |
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
    ' "${manifest_files[@]}" >"${schema_directory}/${xrd_group}/${xrd_resource_kind}_${xrd_version}.json"
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
  ' "${manifest_files[@]}" | sort -u
)

kubeconform "${kubeconform_flags[@]}" "${manifest_directory}"
