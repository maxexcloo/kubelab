import base64
import copy
import json
import os
import secrets
import ssl
import urllib.error
import urllib.request
from urllib.parse import urlsplit

ANNOTATION_PREFIX = "onepassword.excloo.dev/"
KUBERNETES_HOST = "https://kubernetes.default.svc"
KUBERNETES_SERVICE_ACCOUNT = "/var/run/secrets/kubernetes.io/serviceaccount"
SECRET_WORDS = {"key", "password", "secret", "token"}


def request(url, *, token, body=None, context=None, method="GET"):
    data = None if body is None else json.dumps(body).encode()
    headers = {"Authorization": f"Bearer {token}"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    api_request = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(
            api_request, context=context, timeout=30
        ) as response:
            content = response.read()
            return None if not content else json.loads(content)
    except urllib.error.HTTPError as error:
        # Connect error bodies can echo submitted credentials.
        error.close()
        raise RuntimeError(f"{method} {url} returned {error.code}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"{method} {url} failed: {error.reason}") from error


def kubernetes_request(path):
    with open(
        f"{KUBERNETES_SERVICE_ACCOUNT}/token",
        encoding="utf-8",
    ) as token_file:
        token = token_file.read()
    context = ssl.create_default_context(cafile=f"{KUBERNETES_SERVICE_ACCOUNT}/ca.crt")
    return request(
        f"{KUBERNETES_HOST}{path}",
        token=token,
        context=context,
    )


def kubernetes_list(path):
    return kubernetes_request(path).get("items", [])


def kubernetes_get(path):
    return kubernetes_request(path)


def connect(path, *, body=None, method="GET"):
    host = os.environ["OP_CONNECT_HOST"].rstrip("/")
    token = os.environ["OP_CONNECT_TOKEN"]
    return request(
        f"{host}/v1{path}",
        token=token,
        body=body,
        method=method,
    )


def annotations(resource):
    return resource.get("metadata", {}).get("annotations", {})


def secret_values(resource, mapping):
    namespace = resource["metadata"]["namespace"]
    resolved = {}
    for label, source in mapping.items():
        name, _, key = source.partition("/")
        secret = kubernetes_request(f"/api/v1/namespaces/{namespace}/secrets/{name}")
        encoded = secret.get("data", {}).get(key)
        if encoded is None:
            raise RuntimeError(
                f"1Password field {label} needs key {key} in secret {namespace}/{name}"
            )
        resolved[label] = base64.b64decode(encoded).decode()
    return resolved


def item_configuration(resource):
    values = annotations(resource)
    return {
        "concealed": set(
            filter(
                None, values.get(f"{ANNOTATION_PREFIX}concealed-fields", "").split(",")
            )
        ),
        "constants": json.loads(values.get(f"{ANNOTATION_PREFIX}constants", "{}")),
        "defaults": json.loads(values.get(f"{ANNOTATION_PREFIX}defaults", "{}")),
        "formats": json.loads(values.get(f"{ANNOTATION_PREFIX}field-formats", "{}")),
        "generate": set(
            filter(
                None, values.get(f"{ANNOTATION_PREFIX}generate-fields", "").split(",")
            )
        ),
        "remove": set(
            filter(None, values.get(f"{ANNOTATION_PREFIX}remove-fields", "").split(","))
        ),
        "title": values.get(f"{ANNOTATION_PREFIX}title"),
        "values": secret_values(
            resource, json.loads(values.get(f"{ANNOTATION_PREFIX}values", "{}"))
        ),
    }


def merge_configuration(item, resource):
    configuration = item_configuration(resource)
    item["concealed"].update(configuration["concealed"])
    item["constants"].update(configuration["constants"])
    item["defaults"].update(configuration["defaults"])
    item["formats"].update(configuration["formats"])
    item["generate"].update(configuration["generate"])
    item["remove"].update(configuration["remove"])
    if configuration["title"]:
        if item["title"] and item["title"] != configuration["title"]:
            raise RuntimeError("1Password item has conflicting owning titles")
        item["title"] = configuration["title"]
    item["values"].update(configuration["values"])


def new_item():
    return {
        "concealed": set(),
        "constants": {},
        "defaults": {},
        "fields": set(),
        "formats": {},
        "generate": set(),
        "login": False,
        "remove": set(),
        "title": None,
        "urls": set(),
        "values": {},
    }


def kustomization_ready(resource):
    metadata = resource.get("metadata", {})
    source_reference = resource.get("spec", {}).get("sourceRef", {})
    status = resource.get("status", {})
    if source_reference.get("kind") != "GitRepository":
        return False
    source_namespace = source_reference.get("namespace", metadata.get("namespace"))
    source = kubernetes_get(
        f"/apis/source.toolkit.fluxcd.io/v1/namespaces/{source_namespace}/"
        f"gitrepositories/{source_reference.get('name')}"
    )
    source_revision = source.get("status", {}).get("artifact", {}).get("revision")
    ready = any(
        condition.get("type") == "Ready" and condition.get("status") == "True"
        for condition in status.get("conditions", [])
    )
    return (
        ready
        and not resource.get("spec", {}).get("suspend", False)
        and not source.get("spec", {}).get("suspend", False)
        and status.get("observedGeneration") == metadata.get("generation")
        and bool(source_revision)
        and status.get("lastAppliedRevision") == source_revision
    )


def kustomizations_ready():
    # Credential consumers come from several Kustomizations, including mini-apps.
    kustomizations = kubernetes_list(
        "/apis/kustomize.toolkit.fluxcd.io/v1/namespaces/flux-system/kustomizations"
    )
    return bool(kustomizations) and all(map(kustomization_ready, kustomizations))


def externally_owned(item):
    return "Homelab" in item.get("tags", [])


def is_dry_run():
    return os.environ.get("DRY_RUN", "false") == "true"


def discover_items():
    desired = {}
    login_items = {}
    categories = {}
    routes = kubernetes_list("/apis/gateway.networking.k8s.io/v1/httproutes")
    namespace_items = {}
    for route in routes:
        reference = annotations(route).get(f"{ANNOTATION_PREFIX}item")
        if reference:
            namespace_items.setdefault(route["metadata"]["namespace"], set()).add(reference)
    resources = kubernetes_list(
        "/apis/external-secrets.io/v1/externalsecrets"
    ) + kubernetes_list("/apis/external-secrets.io/v1alpha1/pushsecrets")
    for resource in resources:
        namespace = resource["metadata"]["namespace"]
        references = []
        if resource["kind"] == "ExternalSecret":
            store = resource.get("spec", {}).get("secretStoreRef", {})
            if store.get("name") != "onepassword":
                continue
            references = [
                data.get("remoteRef", {})
                for data in resource.get("spec", {}).get("data", [])
            ] + [
                {"key": data.get("extract", {}).get("key")}
                for data in resource.get("spec", {}).get("dataFrom", [])
            ]
        else:
            stores = resource.get("spec", {}).get("secretStoreRefs", [])
            if not any(store.get("name") == "onepassword" for store in stores):
                continue
            references = [
                data.get("match", {}).get("remoteRef", {})
                for data in resource.get("spec", {}).get("data", [])
            ]
        titles = {
            reference.get("key") or reference.get("remoteKey")
            for reference in references
        } - {None}
        owning_items = titles & namespace_items.get(namespace, set())
        owner_title = annotations(resource).get(f"{ANNOTATION_PREFIX}item")
        if owner_title and owner_title not in titles:
            raise RuntimeError("1Password secret owner must be one of its item references")
        if not owner_title and len(owning_items) == 1:
            owner_title = next(iter(owning_items))
        for reference in references:
            title = reference.get("key") or reference.get("remoteKey")
            field = reference.get("property")
            if not title:
                continue
            item = desired.setdefault(title, new_item())
            if title == owner_title:
                merge_configuration(item, resource)
                login_item = annotations(resource).get(f"{ANNOTATION_PREFIX}login-item")
                if login_item:
                    login_items[title] = login_item
            if field:
                item["fields"].add(field)
    # References own credential identity; only an explicit title renames an item.
    for route in routes:
        namespace = route["metadata"]["namespace"]
        route_annotations = annotations(route)
        title = route_annotations.get(f"{ANNOTATION_PREFIX}item")
        if not title:
            continue
        urls = {
            f"https://{hostname}"
            for hostname in route.get("spec", {}).get("hostnames", [])
        }
        if not urls:
            raise RuntimeError(
                f"1Password route {namespace}/{route['metadata']['name']} has no URL"
            )
        item = desired.setdefault(title, new_item())
        display_title = route_annotations.get(f"{ANNOTATION_PREFIX}title")
        if display_title:
            if item["title"] and item["title"] != display_title:
                raise RuntimeError(f"1Password item {title} has conflicting titles")
            item["title"] = display_title
        category = route_annotations.get(f"{ANNOTATION_PREFIX}category", "LOGIN")
        if category not in {"LOGIN", "SERVER"}:
            raise RuntimeError(
                f"1Password route {namespace}/{route['metadata']['name']} has unsupported category {category}"
            )
        if title in categories and categories[title] != category:
            raise RuntimeError(
                f"1Password item {title} has conflicting route categories"
            )
        categories[title] = category
        item["login"] = category == "LOGIN"
        item["urls"].update(urls)
    for title, login_item in login_items.items():
        if login_item not in desired or not desired[login_item]["urls"]:
            raise RuntimeError(
                f"1Password item {title} references missing login item {login_item}"
            )
        desired[title]["urls"].update(desired[login_item]["urls"])
        desired[title]["login"] = desired[login_item]["login"]
    return desired


def field_label(field):
    return field.get("label") or field.get("id")


# Field names: provider-<provider>[-<number>]-api-key or -<token-type>-token for
# upstream credentials in the consuming app's item; virtual-key-<consumer> and
# master-key in the issuing gateway's item.
def group_fields(item):
    sections = {section.get("label"): section for section in item.get("sections", [])}
    for field in item.get("fields", []):
        label = field_label(field)
        if (
            field.get("purpose")
            or field.get("id") == "notesPlain"
            or label.casefold() in {"password", "url", "username"}
        ):
            continue
        if label.startswith("provider-"):
            group = "Providers"
        elif label.startswith("virtual-key-"):
            group = "Virtual Keys"
        elif label.startswith("database-"):
            group = "Database"
        elif label.startswith(("oauth-", "oidc-", "openid-")):
            group = "Authentication"
        elif label in {"master-key", "salt-key"}:
            group = "Administration"
        else:
            group = "Application"
        section = sections.setdefault(
            group, {"id": group.lower().replace(" ", "-"), "label": group}
        )
        if field.get("section", {}).get("id") != section["id"]:
            field["section"] = {"id": section["id"]}
    used = {field.get("section", {}).get("id") for field in item.get("fields", [])}
    item["sections"] = sorted(
        (section for section in sections.values() if section["id"] in used),
        key=lambda section: section.get("label", "").casefold(),
    )


def sort_fields(fields):
    sections = {}
    for index, field in enumerate(fields):
        if (
            field.get("purpose")
            or field.get("id") == "notesPlain"
            or field_label(field).casefold() in {"password", "url", "username"}
        ):
            continue
        sections.setdefault((field.get("section") or {}).get("id"), []).append(index)
    for indices in sections.values():
        ordered = sorted(
            (fields[index] for index in indices),
            key=lambda field: field_label(field).casefold(),
        )
        for index, field in zip(indices, ordered):
            fields[index] = field


# Any key, password, secret or token word conceals a field unless it names an
# identifier; concealed-fields covers secrets with neutral names, such as URLs.
def field_type(label, concealed=frozenset()):
    words = label.split("-")
    secret = words[-1] != "id" and not SECRET_WORDS.isdisjoint(words)
    if secret or label in concealed or label == "certificate-base64":
        return "CONCEALED"
    return "STRING"


def generated_field(label, *, field_format=None, value=None):
    native = label in {"password", "username"}
    field = {"id": label, "label": label, "type": field_type(label)}
    if native:
        field["purpose"] = label.upper()
    if value is None and field_format == "laravel":
        field["value"] = "base64:" + base64.b64encode(secrets.token_bytes(32)).decode()
    elif value is None:
        field["generate"] = True
        field["recipe"] = {
            "characterSets": (
                ["DIGITS", "LETTERS"]
                if field_format == "alphanumeric"
                else ["DIGITS", "LETTERS", "SYMBOLS"]
            ),
            "length": 48,
        }
    else:
        field["value"] = value
    return field


def reconcile_urls(item, desired, *, allow_removal):
    existing = item.setdefault("urls", [])
    if not desired:
        if allow_removal:
            item["urls"] = []
        return
    urls = {url["href"]: copy.deepcopy(url) for url in existing if url.get("href")}
    reconciled = []
    for href in sorted(desired):
        website = urls.get(href)
        if website is None:
            target = urlsplit(href)
            # Carry presentation across a cluster alias rename, never credentials.
            previous = [
                url
                for old, url in urls.items()
                if old not in desired
                and urlsplit(old).scheme == target.scheme
                and urlsplit(old).path == target.path
                and urlsplit(old).hostname
                and target.hostname
                and urlsplit(old).hostname.split(".")[0]
                == target.hostname.split(".")[0]
                and urlsplit(old).hostname.endswith(".excloo.dev")
                and target.hostname.endswith(".excloo.dev")
            ]
            website = copy.deepcopy(previous[0]) if len(previous) == 1 else {}
            website["href"] = href
        reconciled.append(website)
    if not allow_removal:
        reconciled.extend(url for href, url in urls.items() if href not in desired)
    primary = next((url for url in reconciled if url.get("primary")), reconciled[0])
    for url in reconciled:
        if url is primary:
            url["primary"] = True
        else:
            url.pop("primary", None)
    item["urls"] = reconciled


def normalise_item(current, title, desired, vault_id, *, allow_removal=False):
    required_fields = (
        desired["fields"]
        | desired["generate"]
        | set(desired["constants"])
        | set(desired["defaults"])
        | set(desired.get("values", {}))
    )
    if desired["remove"] & required_fields:
        raise RuntimeError(f"1Password item {title} cannot remove referenced fields")
    if set(desired["formats"].values()) - {"alphanumeric", "laravel"}:
        raise RuntimeError(f"1Password item {title} has unsupported field formats")
    current["category"] = "LOGIN" if desired["login"] else "SERVER"
    current.setdefault("tags", ["Kubelab"])
    current["title"] = desired.get("title") or current.get("title") or title
    current.setdefault("vault", {"id": vault_id})
    reconcile_urls(current, desired["urls"], allow_removal=allow_removal)
    fields = current.setdefault("fields", [])
    if allow_removal:
        fields[:] = [
            field for field in fields if field_label(field) not in desired["remove"]
        ]
    if not desired["login"]:
        # Server items have no empty sign-in placeholders; retain real credentials.
        fields[:] = [
            field
            for field in fields
            if field_label(field) not in {"password", "username"}
            or field_label(field) in required_fields
            or field.get("value")
            or field.get("generate")
        ]
    by_label = {field_label(field): field for field in fields}
    for label in sorted(required_fields):
        field = by_label.get(label)
        if label in desired.get("values", {}):
            replacement = generated_field(label, value=desired["values"][label])
        elif label in desired["constants"]:
            replacement = generated_field(label, value=desired["constants"][label])
        elif field and (field.get("value") or field.get("generate")):
            continue
        elif label in desired["defaults"]:
            replacement = generated_field(label, value=desired["defaults"][label])
        elif label in desired["generate"]:
            replacement = generated_field(
                label, field_format=desired["formats"].get(label)
            )
        else:
            # Referenced external credentials get a placeholder, never a random value.
            replacement = generated_field(label, value="")
        if field is not None:
            # Preserve IDs, sections and presentation of existing fields.
            field.update(
                {
                    key: value
                    for key, value in replacement.items()
                    if key in {"value", "generate", "recipe"}
                }
            )
        else:
            if current["category"] != "LOGIN":
                replacement.pop("purpose", None)
            fields.append(replacement)
    for field in fields:
        label = field_label(field)
        # Specialised field types, such as one-time passwords, keep their type.
        if field.get("id") != "notesPlain" and field.get("type", "STRING") in {
            "CONCEALED",
            "STRING",
        }:
            field["type"] = field_type(label, desired.get("concealed", set()))
        if label in {"username", "password"}:
            if desired["login"]:
                field["purpose"] = label.upper()
            else:
                field.pop("purpose", None)
    group_fields(current)
    sort_fields(fields)
    return current


def comparable(item):
    ignored = {"createdAt", "lastEditedBy", "updatedAt", "version"}
    result = {key: value for key, value in item.items() if key not in ignored}
    result["sections"] = result.get("sections") or []
    result["urls"] = result.get("urls") or []
    return result


def check_references(desired, summaries):
    by_id = {summary["id"]: summary for summary in summaries}
    by_title = {}
    for summary in summaries:
        title = summary["title"]
        if title in by_title:
            raise RuntimeError(f"duplicate 1Password item title: {title}")
        by_title[title] = summary
    for reference, configuration in desired.items():
        summary = by_id.get(reference)
        if summary is None:
            raise RuntimeError(f"referenced 1Password item ID {reference} is missing")
        title = configuration.get("title")
        if title in by_title and by_title[title]["id"] != summary["id"]:
            raise RuntimeError(f"1Password title {title} belongs to another item")


def main():
    dry_run = is_dry_run()
    vaults = connect("/vaults")
    if len(vaults) != 1:
        raise RuntimeError(
            f"Connect token must expose exactly one vault; found {len(vaults)}"
        )
    vault_id = vaults[0]["id"]
    desired = discover_items()
    summaries = connect(f"/vaults/{vault_id}/items")
    check_references(desired, summaries)
    try:
        archive_ready = kustomizations_ready()
    except RuntimeError as error:
        archive_ready = False
        print(f"skipped removals because Flux readiness could not be read: {error}")
    else:
        if not archive_ready:
            print("skipped removals because Flux Kustomizations are not fully reconciled")
    changed = 0
    for reference, configuration in sorted(desired.items()):
        current = connect(f"/vaults/{vault_id}/items/{reference}")
        if externally_owned(current):
            continue
        wanted = normalise_item(
            copy.deepcopy(current),
            reference,
            configuration,
            vault_id,
            allow_removal=archive_ready,
        )
        if not archive_ready:
            # A rename waits until Flux has updated every credential consumer.
            wanted["title"] = current["title"]
        if current.get("category") != wanted["category"]:
            # Connect cannot change a category in place; replacing the item would
            # change the ID its consumers reference.
            raise RuntimeError(f"1Password item {reference} has the wrong category")
        if comparable(current) == comparable(wanted):
            continue
        if not dry_run:
            connect(
                f"/vaults/{vault_id}/items/{reference}",
                body=wanted,
                method="PUT",
            )
        changed += 1
        prefix = "would be " if dry_run else ""
        print(f"{wanted['title']} {prefix}updated")
    if not archive_ready:
        print(f"reconciled {len(desired)} items; changed {changed}")
        return
    for summary in sorted(summaries, key=lambda item: item["title"].lower()):
        title = summary["title"]
        if summary["id"] in desired:
            continue
        current = connect(f"/vaults/{vault_id}/items/{summary['id']}")
        if current.get("tags") != ["Kubelab"]:
            continue
        if not dry_run:
            connect(f"/vaults/{vault_id}/items/{summary['id']}", method="DELETE")
        changed += 1
        prefix = "would be " if dry_run else ""
        print(f"{title} {prefix}archived")
    print(f"reconciled {len(desired)} items; changed {changed}")


if __name__ == "__main__":
    main()
