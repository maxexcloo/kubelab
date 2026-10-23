# Resolve monitoring header Secret references to 1Password references so
# consumers need not interpret ExternalSecret and SecretStore manifests.
def single($description):
  if length == 1 then .[0] else error("expected one \($description)") end;

def onepassword_reference($route; $reference):
  ($resources | map(select(
    .kind == "ExternalSecret" and
    .cluster == $route.cluster and
    .metadata.namespace == $route.namespace and
    (.spec.target.name // .metadata.name) == $reference.name
  )) | single("ExternalSecret for \($route.namespace)/\($reference.name)")) as $secret |
  $secret.spec.secretStoreRef as $store_reference |
  ($store_reference.kind // "SecretStore") as $store_kind |
  ($resources | map(select(
    .kind == $store_kind and
    .cluster == $route.cluster and
    .metadata.name == $store_reference.name and
    ($store_kind == "ClusterSecretStore" or .metadata.namespace == $route.namespace)
  )) | single("\($store_kind) \($store_reference.name)")) as $store |
  ($store.spec.provider.onepassword.vaults // {} | keys |
    single("1Password vault for \($store_kind) \($store_reference.name)")) as $vault |
  ([$secret.spec.data[]? | select(.secretKey == $reference.key)] |
    single("data mapping for \($route.namespace)/\($reference.name)/\($reference.key)")) as $mapping |
  if $secret.spec.target.template then
    error("monitoring secrets must use direct ExternalSecret data mappings: \($route.source)")
  elif $mapping.sourceRef then
    error("unsupported monitoring secret mapping: \($route.namespace)/\($reference.name)/\($reference.key)")
  else
    "op://\($vault)/\($mapping.remoteRef.key)/\($mapping.remoteRef.property)"
  end;

map(
  . as $route |
  .headers |= with_entries(
    if (.key | test("^[!#$%&'*+.^_`|~0-9a-zA-Z-]+$") | not) then
      error("invalid monitoring header name: \($route.source)")
    elif (.value | type) != "object" or (.value | keys) != ["key", "name"] then
      error("monitoring headers require a namespace-local Secret name and key: \($route.source)")
    else
      .value = onepassword_reference($route; .value)
    end
  )
) |
sort_by(.cluster // "", .group, .name, .source)
