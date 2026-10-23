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


def field_list(values, name):
    return set(filter(None, values.get(f"{ANNOTATION_PREFIX}{name}", "").split(",")))


def item_configuration(resource):
    values = annotations(resource)
    defaults = json.loads(values.get(f"{ANNOTATION_PREFIX}defaults", "{}"))
    owner_email_fields = field_list(values, "owner-email-fields")
    if owner_email_fields:
        owner_email = os.environ["OWNER_EMAIL"]
        defaults.update(dict.fromkeys(owner_email_fields, owner_email))
    return {
        "concealed": field_list(values, "concealed-fields"),
        "constants": json.loads(values.get(f"{ANNOTATION_PREFIX}constants", "{}")),
        "defaults": defaults,
        "formats": json.loads(values.get(f"{ANNOTATION_PREFIX}field-formats", "{}")),
        "generate": field_list(values, "generate-fields"),
    }


def merge_configuration(item, resource):
    configuration = item_configuration(resource)
    item["concealed"].update(configuration["concealed"])
    item["constants"].update(configuration["constants"])
    item["defaults"].update(configuration["defaults"])
    item["formats"].update(configuration["formats"])
    item["generate"].update(configuration["generate"])


def new_item():
    return {
        "concealed": set(),
        "constants": {},
        "defaults": {},
        "extracted": False,
        "fields": set(),
        "formats": {},
        "generate": set(),
        "login": False,
        "pushed": set(),
        "urls": set(),
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
    # Credential consumers come from several Kustomizations, including minilab.
    kustomizations = kubernetes_list(
        "/apis/kustomize.toolkit.fluxcd.io/v1/namespaces/flux-system/kustomizations"
    )
    return bool(kustomizations) and all(map(kustomization_ready, kustomizations))


def helm_release_ready(resource):
    metadata = resource.get("metadata", {})
    status = resource.get("status", {})
    return (
        any(
            condition.get("type") == "Ready" and condition.get("status") == "True"
            for condition in status.get("conditions", [])
        )
        and not resource.get("spec", {}).get("suspend", False)
        and status.get("observedGeneration") == metadata.get("generation")
    )


def helm_releases_ready():
    # Charts render ExternalSecrets, so an upgrade in progress can hide references.
    releases = kubernetes_list("/apis/helm.toolkit.fluxcd.io/v2/helmreleases")
    return all(map(helm_release_ready, releases))


def flux_ready():
    return kustomizations_ready() and helm_releases_ready()


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
            namespace_items.setdefault(route["metadata"]["namespace"], set()).add(
                reference
            )
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
            ]
            for data in resource.get("spec", {}).get("dataFrom", []):
                title = data.get("extract", {}).get("key")
                if title:
                    desired.setdefault(title, new_item())["extracted"] = True
                    references.append({"key": title})
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
            raise RuntimeError(
                "1Password secret owner must be one of its item references"
            )
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
                if resource["kind"] == "PushSecret":
                    item["pushed"].add(field)
    # References are item titles in the cluster vault.
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
                and len(target.hostname.split(".")) >= 4
                and urlsplit(old).hostname.split(".", 2)[2:]
                == target.hostname.split(".", 2)[2:]
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
    )
    if set(desired["formats"].values()) - {"alphanumeric", "laravel"}:
        raise RuntimeError(f"1Password item {title} has unsupported field formats")
    current["category"] = "LOGIN" if desired["login"] else "SERVER"
    current.setdefault("tags", ["Kubelab"])
    current.setdefault("vault", {"id": vault_id})
    reconcile_urls(current, desired["urls"], allow_removal=allow_removal)
    fields = current.setdefault("fields", [])
    # Extracted items publish every field, so none of their fields is unreferenced.
    if allow_removal and not desired.get("extracted"):
        # Unreferenced credentials go once every consumer is current; sign-in
        # details, notes and specialised fields, such as one-time passwords, remain.
        fields[:] = [
            field
            for field in fields
            if field_label(field) in required_fields
            or field.get("purpose")
            or field.get("id") == "notesPlain"
            or field_label(field).casefold() in {"password", "username"}
            or field.get("type", "STRING") not in {"CONCEALED", "STRING"}
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
        if label in desired["constants"]:
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


# ESO creates a missing item as a SERVER item when a PushSecret publishes first.
# Such an item holds nothing but published values, so it can be replaced safely.
def replaceable(item, desired):
    return item.get("tags") == ["Kubelab"] and all(
        field_label(field) in desired.get("pushed", set())
        for field in item.get("fields", [])
        if field.get("value") or field.get("generate")
    )


def item_ids(desired, summaries):
    ids = {}
    for summary in summaries:
        title = summary["title"]
        if title in ids:
            raise RuntimeError(f"duplicate 1Password item title: {title}")
        ids[title] = summary["id"]
    missing = sorted(set(desired) - set(ids))
    if missing:
        raise RuntimeError(
            f"referenced 1Password items are missing: {', '.join(missing)}"
        )
    return ids


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
    ids = item_ids(desired, summaries)
    try:
        archive_ready = flux_ready()
    except RuntimeError as error:
        archive_ready = False
        print(f"skipped removals because Flux readiness could not be read: {error}")
    else:
        if not archive_ready:
            print("skipped removals because Flux resources are not fully reconciled")
    changed = 0
    for title, configuration in sorted(desired.items()):
        current = connect(f"/vaults/{vault_id}/items/{ids[title]}")
        if externally_owned(current):
            continue
        wanted = normalise_item(
            copy.deepcopy(current),
            title,
            configuration,
            vault_id,
            allow_removal=archive_ready,
        )
        replace = current.get("category") != wanted["category"]
        if replace and not replaceable(current, configuration):
            # Connect cannot change a category in place; replacing the item would
            # discard its history and generated credentials.
            raise RuntimeError(f"1Password item {title} has the wrong category")
        if comparable(current) == comparable(wanted):
            continue
        if not dry_run:
            # Connect replaces the whole item; leave concurrent edits for the next run.
            latest = connect(f"/vaults/{vault_id}/items/{ids[title]}")
            if latest.get("version") != current.get("version"):
                print(f"{title} changed during reconciliation; skipped")
                continue
            if replace:
                # Create first; consumers retry while both titles briefly exist.
                for key in ("createdAt", "id", "lastEditedBy", "updatedAt", "version"):
                    wanted.pop(key, None)
                connect(f"/vaults/{vault_id}/items", body=wanted, method="POST")
                connect(f"/vaults/{vault_id}/items/{ids[title]}", method="DELETE")
            else:
                connect(
                    f"/vaults/{vault_id}/items/{ids[title]}",
                    body=wanted,
                    method="PUT",
                )
        changed += 1
        prefix = "would be " if dry_run else ""
        action = "recreated" if replace else "updated"
        print(f"{wanted['title']} {prefix}{action}")
    if not archive_ready:
        print(f"reconciled {len(desired)} items; changed {changed}")
        return
    for summary in sorted(summaries, key=lambda item: item["title"].lower()):
        title = summary["title"]
        if title in desired:
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
