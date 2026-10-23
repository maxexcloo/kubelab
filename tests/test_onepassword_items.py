"""Tests for the 1Password item reconciler."""

import base64
import contextlib
import copy
import importlib.util
import io
import json
import re
import subprocess
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

ITEM_ID = r"^[a-z0-9]{26}$"
REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
RECONCILER_PATH = REPOSITORY_ROOT / "platform/secrets/onepassword-items/reconcile.py"
SPEC = importlib.util.spec_from_file_location("onepassword_items", RECONCILER_PATH)
RECONCILER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RECONCILER)


def item_configuration(**overrides):
    configuration = {
        "concealed": set(),
        "constants": {},
        "defaults": {},
        "fields": set(),
        "formats": {},
        "generate": set(),
        "login": False,
        "pushed": set(),
        "urls": set(),
    }
    configuration.update(overrides)
    return configuration


class ReconcilerTests(unittest.TestCase):
    def test_all_managed_routes_reference_items_by_display_name(self):
        from support import CLUSTERS, repository_resources

        resources = [
            resource
            for cluster in CLUSTERS
            for path in (f"apps/overlays/{cluster}", f"clusters/{cluster}/platform")
            for resource in repository_resources(path)
        ]
        routes = []
        for resource in resources:
            if resource["kind"] == "HTTPRoute":
                routes.append(copy.deepcopy(resource))
            elif resource["kind"] == "HelmRelease":
                for values in (
                    resource.get("spec", {}).get("values", {}).get("route", {}).values()
                ):
                    routes.append(
                        {
                            "metadata": {
                                "annotations": copy.deepcopy(
                                    values.get("annotations", {})
                                ),
                                "name": resource["metadata"]["name"],
                                "namespace": resource["metadata"]["namespace"],
                            },
                            "spec": {"hostnames": values.get("hostnames", [])},
                        }
                    )
        managed = [
            r
            for r in routes
            if "onepassword.excloo.dev/item" in r["metadata"].get("annotations", {})
        ]
        self.assertGreaterEqual(len(managed), 20)
        for route in managed:
            annotations = route["metadata"]["annotations"]
            # Items may add a bracketed qualifier that the card's location tag shows.
            self.assertRegex(
                annotations["onepassword.excloo.dev/item"],
                rf"^{re.escape(annotations['gethomepage.dev/name'])}( \(.+\))?$",
            )
            self.assertNotIn("onepassword.excloo.dev/title", annotations)
        secrets = [
            r
            for r in resources
            if r["kind"] == "ExternalSecret"
            and r["spec"].get("secretStoreRef", {}).get("name") == "onepassword"
        ]
        for secret in secrets:
            self.assertNotIn(
                "onepassword.excloo.dev/title",
                secret["metadata"].get("annotations", {}),
            )
            for data in secret["spec"].get("data", []):
                self.assertNotRegex(data["remoteRef"]["key"], ITEM_ID)
        for resource in resources:
            if resource["kind"] == "ResendKey":
                self.assertNotRegex(resource["spec"]["item"], ITEM_ID)
            if resource["kind"] in {"B2ObjectStorage", "ResendKey"}:
                self.assertNotIn("displayName", resource["spec"])

    def test_secret_ownership_preserves_generation_for_multiple_items(self):
        owner, shared = "Application", "Shared"
        secret = {
            "kind": "ExternalSecret",
            "metadata": {
                "name": "app",
                "namespace": "app",
                "annotations": {"onepassword.excloo.dev/generate-fields": "password"},
            },
            "spec": {
                "secretStoreRef": {"name": "onepassword"},
                "data": [
                    {"remoteRef": {"key": owner, "property": "password"}},
                    {"remoteRef": {"key": shared, "property": "token"}},
                ],
            },
        }
        route = {
            "metadata": {
                "name": "app",
                "namespace": "app",
                "annotations": {
                    "gethomepage.dev/name": owner,
                    "onepassword.excloo.dev/item": owner,
                },
            },
            "spec": {"hostnames": ["app.example.net"]},
        }
        with patch.object(
            RECONCILER,
            "kubernetes_list",
            side_effect=lambda p: (
                [route]
                if "httproutes" in p
                else [secret]
                if p.endswith("/externalsecrets")
                else []
            ),
        ):
            desired = RECONCILER.discover_items()
        self.assertEqual(desired[owner]["generate"], {"password"})
        self.assertEqual(desired[shared]["generate"], set())

    def test_items_are_found_by_title_and_never_renamed(self):
        current = {
            "category": "LOGIN",
            "fields": [
                {"id": "password", "label": "password", "value": "keep-password"}
            ],
            "id": "item-id",
            "tags": ["Kubelab"],
            "title": "Application",
            "urls": [
                {"href": "https://old.example.net", "label": "Sign In", "primary": True}
            ],
            "vault": {"id": "vault"},
        }
        desired = {
            "Application": item_configuration(
                fields={"password"},
                login=True,
                urls={"https://app.example.net"},
            )
        }
        writes = []

        def connect(path, *, body=None, method="GET"):
            if path == "/vaults":
                return [{"id": "vault"}]
            if path == "/vaults/vault/items":
                return [{key: current[key] for key in ["id", "title"]}]
            self.assertEqual(path, "/vaults/vault/items/item-id")
            if method == "PUT":
                writes.append(copy.deepcopy(body))
                current.clear()
                current.update(copy.deepcopy(body))
            else:
                self.assertEqual(method, "GET")
            return copy.deepcopy(current)

        with (
            patch.object(RECONCILER, "connect", side_effect=connect),
            patch.object(RECONCILER, "discover_items", return_value=desired),
            patch.object(RECONCILER, "flux_ready", return_value=True),
            patch.object(RECONCILER, "is_dry_run", return_value=False),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            RECONCILER.main()
            RECONCILER.main()
        self.assertEqual(len(writes), 1)
        self.assertEqual(current["id"], "item-id")
        self.assertEqual(current["title"], "Application")
        self.assertEqual(current["fields"][0]["value"], "keep-password")
        self.assertEqual(
            current["urls"], [{"href": "https://app.example.net", "primary": True}]
        )

    def test_grouping_preserves_websites_and_credentials_and_removes_empty_groups(self):
        current = {
            "fields": [
                {"id": "username", "label": "username", "value": "keep-user"},
                {"id": "p", "label": "provider-unifi-password", "value": "keep-p"},
                {"id": "v", "label": "virtual-key-pi", "value": "keep-v"},
                {"id": "a", "label": "oauth-client-secret", "value": "keep-a"},
                {"id": "o", "label": "oidc-client-secret", "value": "keep-o"},
                {"id": "s", "label": "openid-session-secret", "value": "keep-s"},
            ],
            "sections": [
                {"id": "empty", "label": "Empty"},
                {"id": "oidc", "label": "OIDC"},
            ],
            "urls": [
                {"href": "https://example.net", "label": "My Website", "primary": True}
            ],
        }
        original = copy.deepcopy(current)
        desired = item_configuration(login=True, urls={"https://example.net"})
        result = RECONCILER.normalise_item(current, "Application", desired, "vault")
        self.assertEqual(result["urls"], original["urls"])
        self.assertEqual(
            [(f["id"], f["value"]) for f in result["fields"]],
            [(f["id"], f["value"]) for f in original["fields"]],
        )
        self.assertEqual(
            [s["label"] for s in result["sections"]],
            ["Authentication", "Providers", "Virtual Keys"],
        )
        self.assertEqual(result["fields"][3]["section"], {"id": "authentication"})
        repeated = RECONCILER.normalise_item(
            copy.deepcopy(result), "Application", desired, "vault"
        )
        self.assertEqual(result, repeated)

    def test_route_urls_follow_cluster_renames_without_losing_presentation(self):
        current = {
            "urls": [
                {
                    "href": "https://app.mbk.internal.example.net",
                    "label": "Private",
                    "primary": True,
                },
                {"href": "https://app.excloo.com", "label": "Public"},
            ]
        }
        desired = item_configuration(
            urls={"https://app.syd.internal.example.net", "https://app.excloo.com"}
        )
        pending = RECONCILER.normalise_item(
            copy.deepcopy(current), "App", desired, "vault"
        )
        self.assertIn(
            "https://app.mbk.internal.example.net",
            [url["href"] for url in pending["urls"]],
        )
        result = RECONCILER.normalise_item(
            copy.deepcopy(current), "App", desired, "vault", allow_removal=True
        )
        self.assertEqual(
            result["urls"],
            [
                {"href": "https://app.excloo.com", "label": "Public"},
                {
                    "href": "https://app.syd.internal.example.net",
                    "label": "Private",
                    "primary": True,
                },
            ],
        )
        repeated = RECONCILER.normalise_item(
            copy.deepcopy(result), "App", desired, "vault", allow_removal=True
        )
        self.assertEqual(result, repeated)
        without_route = item_configuration()
        removed = RECONCILER.normalise_item(
            copy.deepcopy(result), "App", without_route, "vault", allow_removal=True
        )
        self.assertEqual(removed["urls"], [])

    def test_server_category_removes_only_unused_empty_login_fields(self):
        current = {
            "fields": [
                {
                    "id": "username",
                    "label": "username",
                    "purpose": "USERNAME",
                    "value": "",
                },
                {
                    "id": "password",
                    "label": "password",
                    "purpose": "PASSWORD",
                    "value": "",
                },
                {"id": "token", "label": "provider-api-key", "value": "keep"},
            ]
        }
        result = RECONCILER.normalise_item(
            copy.deepcopy(current), "App", item_configuration(), "vault"
        )
        self.assertEqual(result["category"], "SERVER")
        self.assertEqual([field["id"] for field in result["fields"]], ["token"])
        current["fields"][1]["value"] = "real-password"
        result = RECONCILER.normalise_item(
            current, "App", item_configuration(fields={"username"}), "vault"
        )
        self.assertEqual(
            {field["id"] for field in result["fields"]},
            {"username", "password", "token"},
        )
        self.assertTrue(all("purpose" not in field for field in result["fields"]))

    def test_explicit_route_category_and_conflicts(self):
        route = {
            "metadata": {
                "name": "app",
                "namespace": "app",
                "annotations": {
                    "onepassword.excloo.dev/item": "App",
                    "onepassword.excloo.dev/category": "SERVER",
                },
            },
            "spec": {"hostnames": ["app.example.net"]},
        }
        routes = [route]
        with patch.object(
            RECONCILER,
            "kubernetes_list",
            side_effect=lambda path: routes if "httproutes" in path else [],
        ):
            self.assertFalse(RECONCILER.discover_items()["App"]["login"])
            other = copy.deepcopy(route)
            other["metadata"]["annotations"]["onepassword.excloo.dev/category"] = (
                "LOGIN"
            )
            routes.append(other)
            with self.assertRaisesRegex(RuntimeError, "conflicting route categories"):
                RECONCILER.discover_items()
            routes.pop()
            route["metadata"]["annotations"]["onepassword.excloo.dev/category"] = (
                "INVALID"
            )
            with self.assertRaisesRegex(RuntimeError, "unsupported category"):
                RECONCILER.discover_items()

    def test_absent_and_empty_sections_do_not_create_perpetual_drift(self):
        current = {"category": "LOGIN", "fields": [], "urls": []}
        wanted = dict(current, sections=[])
        self.assertEqual(RECONCILER.comparable(current), RECONCILER.comparable(wanted))
        current["sections"] = None
        self.assertEqual(RECONCILER.comparable(current), RECONCILER.comparable(wanted))
        wanted["sections"] = [{"id": "providers", "label": "Providers"}]
        self.assertNotEqual(
            RECONCILER.comparable(current), RECONCILER.comparable(wanted)
        )

    def test_external_credentials_get_empty_placeholders_without_overwriting_values(
        self,
    ):
        desired = item_configuration(
            fields={"certificate-base64", "external-token", "password"}
        )
        current = {
            "fields": [{"id": "password", "label": "password", "value": "keep-me"}]
        }
        result = RECONCILER.normalise_item(current, "Application", desired, "vault")
        fields = {field["label"]: field for field in result["fields"]}
        self.assertEqual(fields["password"]["value"], "keep-me")
        self.assertEqual(fields["external-token"]["value"], "")
        self.assertEqual(fields["external-token"]["type"], "CONCEALED")
        self.assertNotIn("generate", fields["external-token"])
        self.assertEqual(fields["certificate-base64"]["type"], "CONCEALED")

    def test_laravel_key_is_generated_once_with_the_required_encoding(self):
        desired = item_configuration(
            fields={"app-key"},
            formats={"app-key": "laravel"},
            generate={"app-key"},
        )
        current = RECONCILER.normalise_item({}, "LaraPaper", desired, "vault")
        key = current["fields"][0]["value"]
        self.assertTrue(key.startswith("base64:"))
        self.assertEqual(
            len(base64.b64decode(key.removeprefix("base64:"), validate=True)), 32
        )
        repeated = RECONCILER.normalise_item(
            copy.deepcopy(current), "LaraPaper", desired, "vault"
        )
        self.assertEqual(repeated, current)
        desired["formats"]["app-key"] = "unsupported"
        with self.assertRaisesRegex(RuntimeError, "unsupported field formats"):
            RECONCILER.normalise_item({}, "LaraPaper", desired, "vault")

    def test_bifrost_virtual_key_is_generated_once_with_its_prefix(self):
        desired = item_configuration(
            fields={"virtual-key"},
            formats={"virtual-key": "bifrost"},
            generate={"virtual-key"},
        )
        current = RECONCILER.normalise_item({}, "Bifrost", desired, "vault")
        self.assertRegex(current["fields"][0]["value"], r"^sk-bf-[0-9a-f]{48}$")
        repeated = RECONCILER.normalise_item(
            copy.deepcopy(current), "Bifrost", desired, "vault"
        )
        self.assertEqual(repeated, current)

    def test_unreferenced_fields_are_pruned_only_when_ready(self):
        desired = item_configuration(fields={"provider-api-key"}, login=True)
        current = {
            "fields": [
                {"id": "notesPlain", "label": "notesPlain", "purpose": "NOTES"},
                {"id": "username", "label": "username", "purpose": "USERNAME"},
                {"id": "password", "label": "password", "purpose": "PASSWORD"},
                {"id": "otp", "label": "one-time password", "type": "OTP"},
                {"id": "kept", "label": "provider-api-key", "value": "keep"},
                {"id": "old", "label": "retired-api-key", "value": "old"},
                {"id": "note", "label": "retired-note", "type": "STRING"},
            ]
        }
        pending = RECONCILER.normalise_item(
            copy.deepcopy(current), "Application", desired, "vault"
        )
        self.assertEqual(len(pending["fields"]), 7)
        ready = RECONCILER.normalise_item(
            copy.deepcopy(current),
            "Application",
            desired,
            "vault",
            allow_removal=True,
        )
        self.assertEqual(
            {field["id"] for field in ready["fields"]},
            {"kept", "notesPlain", "otp", "password", "username"},
        )

    def test_papra_provider_template_preserves_settings_and_escapes_credentials(self):
        from support import repository_resources

        resource = next(
            resource
            for resource in repository_resources("apps/overlays/syd")
            if resource["kind"] == "ExternalSecret"
            and resource["metadata"]["name"] == "papra"
        )
        credentials = {
            "AUTH_SECRET": "fixture-auth-secret",
            "OPENROUTER_API_KEY": "fixture-api-key",
            "oidc-client-secret": 'fixture"\\secret',
        }
        templates = resource["spec"]["target"]["template"]["data"]
        with tempfile.TemporaryDirectory() as directory:
            chart = Path(directory)
            (chart / "templates").mkdir()
            (chart / "Chart.yaml").write_text(
                "apiVersion: v2\nname: fixture\nversion: 0.1.0\n"
            )
            (chart / "values.yaml").write_text(json.dumps({"credentials": credentials}))
            definitions = "\n".join(
                '{{- define "' + name + '" -}}' + template + "{{- end -}}"
                for name, template in templates.items()
            )
            data = "\n".join(
                "  "
                + name
                + ': {{ include "'
                + name
                + '" .Values.credentials | quote }}'
                for name in templates
            )
            (chart / "templates/secret.yaml").write_text(
                definitions
                + "\napiVersion: v1\nkind: Secret\nmetadata:\n  name: fixture\nstringData:\n"
                + data,
            )
            rendered = subprocess.check_output(
                ["helm", "template", "fixture", str(chart)], text=True
            )
        actual = json.loads(
            subprocess.check_output(
                ["yq", "-o=json", ".stringData"],
                input=rendered,
                text=True,
            )
        )
        self.assertEqual(
            json.loads(actual["AUTH_PROVIDERS_CUSTOMS"]),
            [
                {
                    "clientId": "papra",
                    "clientSecret": credentials["oidc-client-secret"],
                    "discoveryUrl": "https://id.excloo.com/.well-known/openid-configuration",
                    "pkce": True,
                    "providerId": "pocket-id",
                    "providerName": "Excloo ID",
                    "scopes": ["openid", "profile", "email"],
                    "type": "oidc",
                }
            ],
        )
        self.assertEqual(actual["AUTH_SECRET"], credentials["AUTH_SECRET"])
        self.assertEqual(
            actual["OPENROUTER_API_KEY"], credentials["OPENROUTER_API_KEY"]
        )
        self.assertEqual(
            set(actual), {"AUTH_PROVIDERS_CUSTOMS", "AUTH_SECRET", "OPENROUTER_API_KEY"}
        )

    def test_http_errors_do_not_expose_response_credentials(self):
        error = urllib.error.HTTPError(
            "http://connect/v1/items",
            400,
            "Bad Request",
            {},
            io.BytesIO(b'{"password": "private-value"}'),
        )
        with (
            patch.object(RECONCILER.urllib.request, "urlopen", side_effect=error),
            self.assertRaisesRegex(RuntimeError, "returned 400$") as caught,
        ):
            RECONCILER.request("http://connect/v1/items", token="private-token")
        self.assertNotIn("private-value", str(caught.exception))
        self.assertTrue(error.closed)

    def test_category_change_stops_instead_of_replacing_the_referenced_item(self):
        item_id = "a" * 26
        current = {
            "category": "SERVER",
            "fields": [
                {"id": "password", "label": "password", "value": "preserve-me"},
                {"id": "oidc-client-id", "label": "oidc-client-id", "value": "pushed"},
            ],
            "id": item_id,
            "tags": ["Kubelab"],
            "title": "Application",
        }
        with (
            patch.object(RECONCILER, "flux_ready", return_value=True),
            patch.object(RECONCILER, "is_dry_run", return_value=False),
            patch.object(
                RECONCILER,
                "discover_items",
                return_value={
                    "Application": item_configuration(
                        login=True, pushed={"oidc-client-id"}
                    )
                },
            ),
            patch.object(
                RECONCILER,
                "connect",
                side_effect=[
                    [{"id": "vault"}],
                    [{"id": item_id, "title": "Application"}],
                    current,
                ],
            ) as connect,
            self.assertRaisesRegex(RuntimeError, "wrong category"),
        ):
            RECONCILER.main()
        self.assertEqual(connect.call_count, 3)

    def test_pushed_server_item_is_recreated_with_the_route_category(self):
        current = {
            "category": "SERVER",
            "fields": [
                {"id": "notesPlain", "label": "notesPlain", "type": "STRING"},
                {"id": "x", "label": "oidc-client-secret", "value": "pushed"},
            ],
            "id": "old",
            "tags": ["Kubelab"],
            "title": "Application",
            "vault": {"id": "vault"},
            "version": 2,
        }
        calls = []

        def connect(path, *, body=None, method="GET"):
            calls.append((method, path, copy.deepcopy(body)))
            if path == "/vaults":
                return [{"id": "vault"}]
            if path == "/vaults/vault/items" and method == "GET":
                return [{"id": "old", "title": "Application"}]
            if path == "/vaults/vault/items/old" and method == "GET":
                return copy.deepcopy(current)
            if method in {"DELETE", "POST"}:
                return None
            self.fail(f"unexpected Connect request: {method} {path}")

        desired = item_configuration(
            fields={"auth-secret", "oidc-client-secret"},
            generate={"auth-secret"},
            login=True,
            pushed={"oidc-client-secret"},
            urls={"https://app.excloo.com"},
        )
        with (
            patch.object(RECONCILER, "flux_ready", return_value=False),
            patch.object(RECONCILER, "is_dry_run", return_value=False),
            patch.object(
                RECONCILER, "discover_items", return_value={"Application": desired}
            ),
            patch.object(RECONCILER, "connect", side_effect=connect),
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            RECONCILER.main()
        writes = [call for call in calls if call[0] != "GET"]
        self.assertEqual(
            [(method, path) for method, path, _ in writes],
            [("POST", "/vaults/vault/items"), ("DELETE", "/vaults/vault/items/old")],
        )
        created = writes[0][2]
        self.assertEqual(created["category"], "LOGIN")
        self.assertNotIn("id", created)
        self.assertNotIn("version", created)
        fields = {field["label"]: field for field in created["fields"]}
        self.assertEqual(fields["oidc-client-secret"]["value"], "pushed")
        self.assertTrue(fields["auth-secret"]["generate"])
        self.assertIn("Application recreated", output.getvalue())

    def test_archival_only_removes_unreferenced_exclusively_managed_items(self):
        items = {
            "stale": {"title": "Stale", "tags": ["Kubelab"]},
            "shared": {"title": "Shared", "tags": ["Kubelab", "Personal"]},
            "homelab": {"title": "Homelab", "tags": ["Homelab"]},
        }
        archived = []

        def connect(path, *, method="GET", body=None):
            if path == "/vaults":
                return [{"id": "vault"}]
            if path == "/vaults/vault/items":
                return [dict(item, id=item_id) for item_id, item in items.items()]
            item_id = path.rsplit("/", 1)[-1]
            if method == "DELETE":
                archived.append(item_id)
                return None
            return copy.deepcopy(items[item_id])

        with (
            patch.object(RECONCILER, "flux_ready", return_value=True),
            patch.object(RECONCILER, "is_dry_run", return_value=False),
            patch.object(RECONCILER, "discover_items", return_value={}),
            patch.object(RECONCILER, "connect", side_effect=connect),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            RECONCILER.main()
        self.assertEqual(archived, ["stale"])

    def test_duplicate_titles_stop_before_any_item_changes(self):
        summaries = [
            {"id": "first", "title": "Application"},
            {"id": "second", "title": "Application"},
        ]
        with (
            patch.object(RECONCILER, "discover_items", return_value={}),
            patch.object(
                RECONCILER, "connect", side_effect=[[{"id": "vault"}], summaries]
            ) as connect,
            self.assertRaisesRegex(RuntimeError, "duplicate 1Password item title"),
        ):
            RECONCILER.main()
        self.assertEqual(connect.call_count, 2)

    def test_main_leaves_externally_owned_existing_item_unchanged(self):
        existing = {
            "category": "LOGIN",
            "fields": [
                {"id": "password", "label": "password", "value": "preserve-me"},
            ],
            "id": "existing-id",
            "sections": [],
            "tags": ["Homelab"],
            "title": "Pocket ID",
        }
        calls = []

        def connect(path, *, body=None, method="GET"):
            calls.append((method, path, body))
            if path == "/vaults":
                return [{"id": "vault"}]
            if path == "/vaults/vault/items":
                return [{"id": "existing-id", "title": existing["title"]}]
            if path == "/vaults/vault/items/existing-id" and method == "GET":
                return dict(existing)
            self.fail(f"unexpected Connect request: {method} {path}")

        desired = item_configuration(
            fields={"password"},
            login=True,
            urls={"https://id.excloo.com"},
        )
        originals = {
            "flux_ready": RECONCILER.flux_ready,
            "connect": RECONCILER.connect,
            "discover_items": RECONCILER.discover_items,
            "is_dry_run": RECONCILER.is_dry_run,
        }
        for name, value in originals.items():
            self.addCleanup(setattr, RECONCILER, name, value)
        RECONCILER.flux_ready = lambda: False
        RECONCILER.connect = connect
        RECONCILER.discover_items = lambda cluster=None: {"Pocket ID": desired}
        RECONCILER.is_dry_run = lambda: False
        with contextlib.redirect_stdout(io.StringIO()):
            RECONCILER.main()
        self.assertFalse(
            any(method in {"DELETE", "POST", "PUT"} for method, _, _ in calls)
        )

    def test_items_edited_during_reconciliation_are_skipped(self):
        current = {
            "category": "SERVER",
            "fields": [],
            "id": "item-id",
            "tags": ["Kubelab"],
            "title": "Application",
            "version": 1,
        }
        writes = []

        def connect(path, *, body=None, method="GET"):
            if path == "/vaults":
                return [{"id": "vault"}]
            if path == "/vaults/vault/items":
                return [{"id": "item-id", "title": "Application"}]
            if method == "PUT":
                writes.append(body)
                return body
            # A person saves the item between the reconciler's read and write.
            item = copy.deepcopy(current)
            current["version"] += 1
            return item

        desired = {"Application": item_configuration(generate={"api-key"})}
        output = io.StringIO()
        with (
            patch.object(RECONCILER, "connect", side_effect=connect),
            patch.object(RECONCILER, "discover_items", return_value=desired),
            patch.object(RECONCILER, "flux_ready", return_value=False),
            patch.object(RECONCILER, "is_dry_run", return_value=False),
            contextlib.redirect_stdout(output),
        ):
            RECONCILER.main()
        self.assertEqual(writes, [])
        self.assertIn(
            "Application changed during reconciliation; skipped", output.getvalue()
        )

    def test_extracted_items_keep_unreferenced_fields(self):
        desired = item_configuration(defaults={"provider-api-key": ""}, extracted=True)
        current = {
            "fields": [
                {"id": "declared", "label": "provider-api-key", "value": "keep"},
                {"id": "manual", "label": "provider-new-api-key", "value": "keep"},
            ]
        }
        result = RECONCILER.normalise_item(
            current, "Homepage", desired, "vault", allow_removal=True
        )
        self.assertEqual(
            {field["id"] for field in result["fields"]}, {"declared", "manual"}
        )

    def test_owner_email_fields_default_to_the_owner_email(self):
        resource = {
            "metadata": {
                "annotations": {
                    "onepassword.excloo.dev/defaults": '{"token":""}',
                    "onepassword.excloo.dev/owner-email-fields": "email,username",
                },
                "namespace": "app",
            }
        }
        with patch.dict(RECONCILER.os.environ, {"OWNER_EMAIL": "owner@example.net"}):
            configuration = RECONCILER.item_configuration(resource)
        self.assertEqual(
            configuration["defaults"],
            {
                "email": "owner@example.net",
                "token": "",
                "username": "owner@example.net",
            },
        )
        with (
            patch.dict(RECONCILER.os.environ, clear=True),
            self.assertRaisesRegex(KeyError, "OWNER_EMAIL"),
        ):
            RECONCILER.item_configuration(resource)

    def test_discovery_uses_secret_owner_and_explicit_route_item(self):
        resources = [
            {
                "kind": "ExternalSecret",
                "metadata": {
                    "annotations": {
                        "onepassword.excloo.dev/generate-fields": "api-key,password",
                    },
                    "name": "comfy-control",
                    "namespace": "comfy-control",
                },
                "spec": {
                    "data": [
                        {
                            "remoteRef": {
                                "key": "Comfy Control",
                                "property": "password",
                            }
                        },
                        {
                            "remoteRef": {
                                "key": "CLIProxyAPI",
                                "property": "api-key",
                            }
                        },
                    ],
                    "secretStoreRef": {"name": "onepassword"},
                },
            }
        ]
        routes = [
            {
                "metadata": {
                    "annotations": {
                        "gethomepage.dev/enabled": "true",
                        "gethomepage.dev/href": "https://comfy.excloo.com",
                        "gethomepage.dev/name": "Renamed Dashboard Card",
                        "onepassword.excloo.dev/item": "Comfy Control",
                    },
                    "name": "comfy-control",
                    "namespace": "comfy-control",
                },
                "spec": {"hostnames": ["comfy.excloo.com"]},
            }
        ]
        original = RECONCILER.kubernetes_list
        self.addCleanup(setattr, RECONCILER, "kubernetes_list", original)
        RECONCILER.kubernetes_list = lambda path: (
            routes if "httproutes" in path else resources
        )
        desired = RECONCILER.discover_items()
        self.assertEqual(desired["Comfy Control"]["urls"], {"https://comfy.excloo.com"})
        self.assertTrue(desired["Comfy Control"]["login"])
        self.assertFalse(desired["CLIProxyAPI"]["login"])

    def test_discovery_recognises_data_from_extract_owner(self):
        resources = [
            {
                "kind": "ExternalSecret",
                "metadata": {
                    "annotations": {
                        "onepassword.excloo.dev/defaults": '{"widget-key":""}',
                        "onepassword.excloo.dev/item": "Homepage",
                    },
                    "name": "homepage",
                    "namespace": "homepage",
                },
                "spec": {
                    "dataFrom": [{"extract": {"key": "Homepage"}}],
                    "secretStoreRef": {"name": "onepassword"},
                },
            }
        ]
        original = RECONCILER.kubernetes_list
        self.addCleanup(setattr, RECONCILER, "kubernetes_list", original)
        RECONCILER.kubernetes_list = lambda path: (
            [] if "httproutes" in path else resources
        )
        desired = RECONCILER.discover_items()
        self.assertEqual(set(desired), {"Homepage"})
        self.assertEqual(desired["Homepage"]["defaults"], {"widget-key": ""})
        self.assertTrue(desired["Homepage"]["extracted"])
        self.assertFalse(desired["Homepage"]["login"])

    def test_discovery_seeds_only_explicit_route_items(self):
        routes = [
            {
                "metadata": {
                    "annotations": {
                        "gethomepage.dev/enabled": "true",
                        "gethomepage.dev/href": "https://headlamp.syd.excloo.dev",
                        "gethomepage.dev/name": "Renamed Dashboard Card",
                        "onepassword.excloo.dev/item": "Headlamp",
                    },
                    "name": "headlamp",
                    "namespace": "headlamp",
                },
                "spec": {"hostnames": ["headlamp.syd.excloo.dev"]},
            },
            {
                "metadata": {
                    "name": "beszel-agent",
                    "namespace": "beszel-agent",
                },
                "spec": {"hostnames": ["beszel-agent.excloo.com"]},
            },
        ]
        original = RECONCILER.kubernetes_list
        self.addCleanup(setattr, RECONCILER, "kubernetes_list", original)
        RECONCILER.kubernetes_list = lambda path: routes if "httproutes" in path else []
        desired = RECONCILER.discover_items()
        self.assertEqual(set(desired), {"Headlamp"})
        self.assertTrue(desired["Headlamp"]["login"])
        self.assertEqual(
            desired["Headlamp"]["urls"],
            {"https://headlamp.syd.excloo.dev"},
        )

    def test_discovery_ignores_dashboard_visibility_names_and_cluster_suffixes(self):
        route = {
            "metadata": {
                "annotations": {
                    "gethomepage.dev/enabled": "false",
                    "gethomepage.dev/name": "Headlamp (SYD)",
                    "gethomepage.dev/href": "https://unrelated.example.net",
                    "onepassword.excloo.dev/item": "Headlamp",
                },
                "name": "renamed-route",
                "namespace": "headlamp",
            },
            "spec": {"hostnames": ["headlamp.example.net"]},
        }
        with patch.object(
            RECONCILER,
            "kubernetes_list",
            side_effect=lambda path: [route] if "httproutes" in path else [],
        ):
            desired = RECONCILER.discover_items()
        self.assertEqual(set(desired), {"Headlamp"})
        self.assertEqual(desired["Headlamp"]["urls"], {"https://headlamp.example.net"})

    def test_secret_can_explicitly_share_another_items_login(self):
        secret = {
            "kind": "ExternalSecret",
            "metadata": {
                "annotations": {
                    "onepassword.excloo.dev/item": "Inventory",
                    "onepassword.excloo.dev/login-item": "Dashboard",
                },
                "name": "inventory",
                "namespace": "homepage",
            },
            "spec": {
                "data": [{"remoteRef": {"key": "Inventory", "property": "notesPlain"}}],
                "secretStoreRef": {"name": "onepassword"},
            },
        }
        route = {
            "metadata": {
                "annotations": {"onepassword.excloo.dev/item": "Dashboard"},
                "name": "homepage",
                "namespace": "homepage",
            },
            "spec": {"hostnames": ["home.example.net"]},
        }
        with patch.object(
            RECONCILER,
            "kubernetes_list",
            side_effect=lambda path: [route] if "httproutes" in path else [secret],
        ):
            desired = RECONCILER.discover_items()
            self.assertEqual(desired["Inventory"]["urls"], {"https://home.example.net"})
            self.assertTrue(desired["Inventory"]["login"])
            route["metadata"]["annotations"].clear()
            with self.assertRaisesRegex(RuntimeError, "references missing login item"):
                RECONCILER.discover_items()

    def test_explicit_route_item_requires_a_url(self):
        route = {
            "metadata": {
                "annotations": {"onepassword.excloo.dev/item": "Application"},
                "name": "application",
                "namespace": "application",
            }
        }
        with (
            patch.object(
                RECONCILER,
                "kubernetes_list",
                side_effect=lambda path: [route] if "httproutes" in path else [],
            ),
            self.assertRaisesRegex(RuntimeError, "has no URL"),
        ):
            RECONCILER.discover_items()

    def test_homelab_tag_defines_external_ownership(self):
        self.assertTrue(RECONCILER.externally_owned({"tags": ["Homelab"]}))
        self.assertFalse(RECONCILER.externally_owned({"tags": ["Kubelab"]}))

    def test_main_skips_archival_until_applications_are_current(self):
        calls = []

        def connect(path, *, body=None, method="GET"):
            calls.append((method, path, body))
            if path == "/vaults":
                return [{"id": "vault"}]
            if path == "/vaults/vault/items":
                return [{"id": "stale", "title": "Stale"}]
            if path == "/vaults/vault/items/stale":
                return {"id": "stale", "tags": ["Kubelab"], "title": "Stale"}
            self.fail(f"unexpected Connect request: {method} {path}")

        originals = {
            "flux_ready": RECONCILER.flux_ready,
            "connect": RECONCILER.connect,
            "discover_items": RECONCILER.discover_items,
            "is_dry_run": RECONCILER.is_dry_run,
        }
        for name, value in originals.items():
            self.addCleanup(setattr, RECONCILER, name, value)
        RECONCILER.flux_ready = lambda: False
        RECONCILER.connect = connect
        RECONCILER.discover_items = lambda cluster=None: {}
        RECONCILER.is_dry_run = lambda: False
        with contextlib.redirect_stdout(io.StringIO()):
            RECONCILER.main()
        self.assertFalse(any(method == "DELETE" for method, _, _ in calls))

    def test_normalisation_preserves_existing_item_and_credentials(self):
        current = {
            "category": "SERVER",
            "id": "existing-id",
            "tags": ["Kubelab", "Personal"],
            "urls": [{"href": "https://old.example.com", "primary": True}],
            "fields": [
                {"id": "password", "label": "password", "value": "edited"},
                {"id": "token", "label": "token", "value": "preserved"},
            ],
            "sections": [],
        }
        desired = item_configuration(
            constants={"database-username": "application"},
            defaults={"username": "admin"},
            fields={
                "api-key",
                "database-password",
                "database-username",
                "password",
                "token",
                "username",
            },
            generate={"api-key", "database-password", "password", "token"},
            login=True,
            urls={"https://application.excloo.com"},
        )
        result = RECONCILER.normalise_item(current, "Application", desired, "vault")
        fields = {field["label"]: field for field in result["fields"]}
        self.assertEqual(result["category"], "LOGIN")
        self.assertEqual(result["id"], "existing-id")
        self.assertEqual(result["tags"], ["Kubelab", "Personal"])
        self.assertEqual(
            result["urls"],
            [
                {"href": "https://application.excloo.com"},
                {"href": "https://old.example.com", "primary": True},
            ],
        )
        self.assertEqual(fields["password"]["value"], "edited")
        self.assertEqual(fields["token"]["value"], "preserved")
        self.assertEqual(fields["username"]["value"], "admin")
        self.assertEqual(fields["database-username"]["value"], "application")
        self.assertTrue(fields["api-key"]["generate"])
        self.assertEqual(
            [field["label"] for field in result["fields"]],
            [
                "password",
                "api-key",
                "token",
                "database-password",
                "database-username",
                "username",
            ],
        )
        repeated = RECONCILER.normalise_item(
            result.copy(),
            "Application",
            desired,
            "vault",
        )
        self.assertEqual(RECONCILER.comparable(result), RECONCILER.comparable(repeated))


if __name__ == "__main__":
    unittest.main()
