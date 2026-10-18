#!/usr/bin/env python3

"""Tests for the 1Password item reconciler."""

import base64
import contextlib
import copy
import importlib.util
import io
import json
import subprocess
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
RECONCILER_PATH = REPOSITORY_ROOT / "platform/secrets/onepassword-items/reconcile.py"
SPEC = importlib.util.spec_from_file_location("onepassword_items", RECONCILER_PATH)
RECONCILER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RECONCILER)


def item_configuration(**overrides):
    configuration = {
        "constants": {},
        "defaults": {},
        "fields": set(),
        "formats": {},
        "generate": set(),
        "login": False,
        "namespaces": set(),
        "remove": set(),
        "urls": set(),
    }
    configuration.update(overrides)
    return configuration


class ReconcilerTests(unittest.TestCase):
    def test_all_managed_routes_use_display_names_and_stable_item_references(self):
        from support import repository_resources

        resources = repository_resources("apps/overlays/syd") + repository_resources("clusters/syd/platform")
        routes = []
        for resource in resources:
            if resource["kind"] == "HTTPRoute":
                routes.append(copy.deepcopy(resource))
            elif resource["kind"] == "HelmRelease":
                for values in resource.get("spec", {}).get("values", {}).get("route", {}).values():
                    routes.append({"metadata": {"annotations": copy.deepcopy(values.get("annotations", {})), "name": resource["metadata"]["name"], "namespace": resource["metadata"]["namespace"]}, "spec": {"hostnames": values.get("hostnames", [])}})
        managed = [r for r in routes if "onepassword.excloo.dev/item" in r["metadata"].get("annotations", {})]
        self.assertGreaterEqual(len(managed), 20)
        for route in managed:
            annotations = route["metadata"]["annotations"]
            self.assertTrue(RECONCILER.is_item_id(annotations["onepassword.excloo.dev/item"]))
            self.assertNotIn("onepassword.excloo.dev/title", annotations)
            annotations["gethomepage.dev/name"] = "Renamed " + annotations["gethomepage.dev/name"]
        secrets = [r for r in resources if r["kind"] == "ExternalSecret" and r["spec"].get("secretStoreRef", {}).get("name") == "onepassword"]
        for secret in secrets:
            for data in secret["spec"].get("data", []):
                self.assertTrue(RECONCILER.is_item_id(data["remoteRef"]["key"]))
        with patch.object(RECONCILER, "kubernetes_list", side_effect=lambda p: routes if "httproutes" in p else secrets if p.endswith("/externalsecrets") else []), \
                patch.object(RECONCILER, "secret_values", side_effect=lambda r, m: {k: "fixture" for k in m}):
            desired = RECONCILER.discover_items()
        for route in managed:
            annotations = route["metadata"]["annotations"]
            self.assertEqual(desired[annotations["onepassword.excloo.dev/item"]]["title"], annotations["gethomepage.dev/name"])
        for resource in resources:
            if resource["kind"] == "ResendKey":
                self.assertTrue(RECONCILER.is_item_id(resource["spec"]["itemID"]))
                self.assertNotIn("displayName", resource["spec"])

    def test_uuid_secret_ownership_preserves_generation_for_multiple_items(self):
        owner, shared = "a" * 26, "b" * 26
        secret = {"kind": "ExternalSecret", "metadata": {"name": "app", "namespace": "app", "annotations": {"onepassword.excloo.dev/generate-fields": "password"}}, "spec": {"secretStoreRef": {"name": "onepassword"}, "data": [{"remoteRef": {"key": owner, "property": "password"}}, {"remoteRef": {"key": shared, "property": "token"}}]}}
        route = {"metadata": {"name": "app", "namespace": "app", "annotations": {"gethomepage.dev/name": "Application", "onepassword.excloo.dev/item": owner}}, "spec": {"hostnames": ["app.example.net"]}}
        with patch.object(RECONCILER, "kubernetes_list", side_effect=lambda p: [route] if "httproutes" in p else [secret] if p.endswith("/externalsecrets") else []):
            desired = RECONCILER.discover_items()
        self.assertEqual(desired[owner]["generate"], {"password"})
        self.assertEqual(desired[shared]["generate"], set())
        self.assertEqual(desired[owner]["title"], "Application")

    def test_display_name_change_keeps_syncthing_resource_and_item_identities(self):
        from support import copy_repository, read_yaml, render_resources

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            copy_repository(root)
            path = root / "apps/overlays/syd/syncthing.yaml"
            settings = read_yaml(path)
            settings["spec"]["values"]["route"]["private"]["annotations"]["gethomepage.dev/name"] = "Syncthing (Archive)"
            path.write_text(json.dumps(settings))
            resources = render_resources(root / "apps/overlays/syd")
        release = next(r for r in resources if r["kind"] == "HelmRelease" and r["metadata"]["name"] == "syncthing")
        secret = next(r for r in resources if r["kind"] == "ExternalSecret" and r["metadata"]["namespace"] == "syncthing")
        annotations = release["spec"]["values"]["route"]["private"]["annotations"]
        self.assertNotIn("onepassword.excloo.dev/title", annotations)
        route = {"metadata": {"namespace": "syncthing", "name": "syncthing", "annotations": annotations}, "spec": {"hostnames": ["syncthing.example.net"]}}
        with patch.object(RECONCILER, "kubernetes_list", side_effect=lambda p: [route] if "httproutes" in p else []):
            desired = RECONCILER.discover_items()
        self.assertEqual(desired[annotations["onepassword.excloo.dev/item"]]["title"], "Syncthing (Archive)")
        self.assertTrue(all(d["remoteRef"]["key"] == annotations["onepassword.excloo.dev/item"] for d in secret["spec"]["data"]))
        self.assertEqual(secret["metadata"]["name"], "syncthing")
        self.assertEqual(release["spec"]["values"]["persistence"]["data"]["existingClaim"], "data")
        self.assertEqual(release["spec"]["values"]["defaultPodOptions"]["nodeSelector"]["kubernetes.io/hostname"], "kimbap")

    def test_item_rename_preserves_identity_credentials_and_consumers(self):
        item_id = "a" * 26
        current = {
            "category": "LOGIN",
            "fields": [{"id": "password", "label": "password", "value": "keep-password"}],
            "id": item_id,
            "tags": ["Kubelab"],
            "title": "Application",
            "urls": [{"href": "https://app.example.net", "label": "Sign In", "primary": True}],
            "vault": {"id": "vault"},
        }
        desired = {item_id: item_configuration(
            fields={"password"}, login=True, title="Application (Kimbap)",
            urls={"https://app.example.net"},
        )}
        writes = []

        def connect(path, *, body=None, method="GET"):
            if path == "/vaults":
                return [{"id": "vault"}]
            if path == "/vaults/vault/items":
                return [{key: current[key] for key in ["id", "title"]}]
            self.assertEqual(path, f"/vaults/vault/items/{item_id}")
            if method == "PUT":
                writes.append(copy.deepcopy(body))
                current.clear()
                current.update(copy.deepcopy(body))
            else:
                self.assertEqual(method, "GET")
            return copy.deepcopy(current)

        readiness = False
        with patch.object(RECONCILER, "connect", side_effect=connect), \
                patch.object(RECONCILER, "discover_items", return_value=desired), \
                patch.object(RECONCILER, "kustomizations_ready", side_effect=lambda: readiness), \
                patch.object(RECONCILER, "is_dry_run", return_value=False), \
                contextlib.redirect_stdout(io.StringIO()):
            RECONCILER.main()
            self.assertEqual(current["title"], "Application")
            readiness = True
            writes.clear()
            RECONCILER.main()
            RECONCILER.main()
        self.assertEqual(len(writes), 1)
        self.assertEqual(current["id"], item_id)
        self.assertEqual(current["title"], "Application (Kimbap)")
        self.assertEqual(current["fields"][0]["value"], "keep-password")
        self.assertEqual(current["urls"], [{"href": "https://app.example.net", "label": "Sign In", "primary": True}])

    def test_item_rename_rejects_conflicts_and_remaining_title_consumers(self):
        item_id = "a" * 26
        summaries = [{"id": item_id, "title": "Application"}, {"id": "other", "title": "Taken"}]
        with self.assertRaisesRegex(RuntimeError, "belongs to another item"):
            RECONCILER.resolve_items({item_id: {"title": "Taken"}}, summaries)
        with self.assertRaisesRegex(RuntimeError, "title-based references"):
            RECONCILER.resolve_items({item_id: {"title": "Renamed"}, "Application": {}}, summaries)
        with self.assertRaisesRegex(RuntimeError, "requires an existing item ID"):
            RECONCILER.resolve_items({"Application": {"title": "Renamed"}}, summaries)
        with self.assertRaisesRegex(RuntimeError, "is missing"):
            RECONCILER.resolve_items({"b" * 26: {}}, summaries)

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
                    "href": "https://app.mbk.excloo.dev",
                    "label": "Private",
                    "primary": True,
                },
                {"href": "https://app.excloo.com", "label": "Public"},
            ]
        }
        desired = item_configuration(
            urls={"https://app.syd.excloo.dev", "https://app.excloo.com"}
        )
        pending = RECONCILER.normalise_item(
            copy.deepcopy(current), "App", desired, "vault"
        )
        self.assertIn(
            "https://app.mbk.excloo.dev", [url["href"] for url in pending["urls"]]
        )
        result = RECONCILER.normalise_item(
            copy.deepcopy(current), "App", desired, "vault", allow_removal=True
        )
        self.assertEqual(
            result["urls"],
            [
                {"href": "https://app.excloo.com", "label": "Public"},
                {
                    "href": "https://app.syd.excloo.dev",
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

    def test_declared_values_overwrite_existing_field_values(self):
        desired = item_configuration(
            fields={"object-storage-secret-access-key"},
            values={"object-storage-secret-access-key": "fresh-value"},
        )
        current = {
            "fields": [
                {
                    "id": "stored",
                    "label": "object-storage-secret-access-key",
                    "value": "stale-value",
                },
            ]
        }
        result = RECONCILER.normalise_item(current, "Beszel", desired, "vault")
        fields = {field["label"]: field for field in result["fields"]}
        self.assertEqual(
            fields["object-storage-secret-access-key"]["value"], "fresh-value"
        )
        self.assertEqual(fields["object-storage-secret-access-key"]["id"], "stored")

    def test_secret_values_resolve_declared_fields(self):
        resource = {"metadata": {"namespace": "beszel"}}
        secret = {
            "data": {"secret-access-key": base64.b64encode(b"fresh-value").decode()}
        }
        with patch.object(
            RECONCILER, "kubernetes_request", return_value=secret
        ) as request:
            resolved = RECONCILER.secret_values(
                resource,
                {
                    "object-storage-secret-access-key": "b2-application-key/secret-access-key"
                },
            )
        self.assertEqual(resolved, {"object-storage-secret-access-key": "fresh-value"})
        request.assert_called_once_with(
            "/api/v1/namespaces/beszel/secrets/b2-application-key"
        )

    def test_missing_secret_values_stop_the_reconcile(self):
        resource = {"metadata": {"namespace": "beszel"}}
        with patch.object(RECONCILER, "kubernetes_request", return_value={"data": {}}):
            with self.assertRaisesRegex(RuntimeError, "needs key access-key-id"):
                RECONCILER.secret_values(
                    resource,
                    {
                        "object-storage-access-key-id": "b2-application-key/access-key-id"
                    },
                )

    def test_interpolated_tokens_use_only_letters_and_digits(self):
        desired = item_configuration(
            fields={"monitoring-token"},
            formats={"monitoring-token": "alphanumeric"},
            generate={"monitoring-token"},
        )
        result = RECONCILER.normalise_item({}, "Redlib", desired, "vault")
        field = result["fields"][0]
        self.assertTrue(field["generate"])
        self.assertEqual(
            field["recipe"], {"characterSets": ["DIGITS", "LETTERS"], "length": 48}
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

    def test_explicit_field_removal_requires_readiness_and_preserves_unrelated_fields(
        self,
    ):
        desired = item_configuration(remove={"duplicate-password"})
        current = {
            "fields": [
                {"id": "old", "label": "duplicate-password", "value": "old-value"},
                {"id": "personal", "label": "personal-token", "value": "keep-me"},
            ]
        }
        pending = RECONCILER.normalise_item(
            copy.deepcopy(current), "Application", desired, "vault"
        )
        self.assertEqual(len(pending["fields"]), 2)
        ready = RECONCILER.normalise_item(
            copy.deepcopy(current),
            "Application",
            desired,
            "vault",
            allow_removal=True,
        )
        self.assertEqual(
            [field["label"] for field in ready["fields"]], ["personal-token"]
        )
        desired["fields"].add("duplicate-password")
        with self.assertRaisesRegex(RuntimeError, "cannot remove referenced fields"):
            RECONCILER.normalise_item(
                current, "Application", desired, "vault", allow_removal=True
            )

    def test_papra_provider_template_preserves_settings_and_escapes_credentials(self):
        manifests = subprocess.check_output(
            ["kubectl", "kustomize", str(REPOSITORY_ROOT / "apps/overlays/syd")],
            text=True,
        )
        resource = json.loads(
            subprocess.check_output(
                [
                    "yq",
                    "-o=json",
                    'select(.kind == "ExternalSecret" and .metadata.name == "papra")',
                ],
                input=manifests,
                text=True,
            )
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
                    "clientId": "papra-au-truenas",
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

    def test_field_sort_preserves_values_ids_sections_and_native_fields(self):
        fields = [
            {"id": "username", "purpose": "USERNAME", "value": "max@example.net"},
            {"id": "z", "label": "Zulu", "value": "keep-z"},
            {"id": "password", "purpose": "PASSWORD", "value": "keep-password"},
            {"id": "website", "label": "URL", "value": "https://example.net"},
            {"id": "b", "label": "beta", "section": {"id": "other"}, "value": "keep-b"},
            {"id": "a", "label": "alpha", "value": "keep-a"},
            {
                "id": "c",
                "label": "Alpha",
                "section": {"id": "other"},
                "value": "keep-c",
            },
            {"id": "notesPlain", "value": "keep-notes"},
        ]
        original = copy.deepcopy(fields)
        RECONCILER.sort_fields(fields)
        self.assertEqual(
            [field["id"] for field in fields],
            ["username", "a", "password", "website", "c", "z", "b", "notesPlain"],
        )
        self.assertEqual(
            {field["id"]: field for field in fields},
            {field["id"]: field for field in original},
        )
        first = copy.deepcopy(fields)
        RECONCILER.sort_fields(fields)
        self.assertEqual(fields, first)

    def test_http_errors_do_not_expose_response_credentials(self):
        error = urllib.error.HTTPError(
            "http://connect/v1/items",
            400,
            "Bad Request",
            {},
            io.BytesIO(b'{"password": "private-value"}'),
        )
        with patch.object(RECONCILER.urllib.request, "urlopen", side_effect=error):
            with self.assertRaisesRegex(RuntimeError, "returned 400$") as caught:
                RECONCILER.request("http://connect/v1/items", token="private-token")
        self.assertNotIn("private-value", str(caught.exception))
        self.assertTrue(error.closed)

    def test_eventual_update_retries_only_not_found(self):
        for code in [400, 404]:
            with (
                self.subTest(code=code),
                patch.object(
                    RECONCILER,
                    "connect",
                    side_effect=[
                        RuntimeError(f"PUT http://connect returned {code}"),
                        {},
                    ],
                ) as connect,
                patch.object(RECONCILER.time, "sleep") as sleep,
            ):
                if code == 404:
                    self.assertEqual(
                        RECONCILER.update_eventually("/items/item", {}), {}
                    )
                    self.assertEqual(connect.call_count, 2)
                    sleep.assert_called_once_with(5)
                else:
                    with self.assertRaises(RuntimeError):
                        RECONCILER.update_eventually("/items/item", {})
                    sleep.assert_not_called()

    def test_category_replacement_preserves_credentials_before_removing_original(self):
        original = {
            "category": "SERVER",
            "id": "original-id",
            "title": "Application",
            "fields": [{"id": "password", "label": "password", "value": "keep-me"}],
            "tags": ["Kubelab"],
            "urls": [],
            "vault": {"id": "vault"},
        }
        replacement = dict(original, category="LOGIN", id="replacement-id")
        replies = [
            [{"id": "vault"}],
            [{"id": "original-id", "title": "Application"}],
            original,
            replacement,
            replacement,
            None,
        ]
        with (
            patch.object(RECONCILER, "kustomizations_ready", return_value=False),
            patch.object(RECONCILER, "is_dry_run", return_value=False),
            patch.object(
                RECONCILER,
                "discover_items",
                return_value={"Application": item_configuration(login=True)},
            ),
            patch.object(RECONCILER, "connect", side_effect=replies) as connect,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            RECONCILER.main()
        writes = connect.call_args_list[3:]
        self.assertEqual(
            [call.kwargs["method"] for call in writes], ["POST", "PUT", "DELETE"]
        )
        self.assertEqual(writes[0].kwargs["body"]["fields"][0]["value"], "keep-me")
        self.assertEqual(writes[1].args[0], "/vaults/vault/items/replacement-id")
        self.assertEqual(writes[2].args[0], "/vaults/vault/items/original-id")

    def test_category_replacement_keeps_original_if_credentials_are_not_saved(self):
        original = {
            "category": "LOGIN",
            "id": "old",
            "title": "App",
            "fields": [
                {"id": "key", "label": "api-key", "value": "keep-me"},
            ],
            "tags": ["Kubelab"],
            "urls": [],
        }
        replies = [
            [{"id": "vault"}],
            [{"id": "old", "title": "App"}],
            original,
            {"id": "new", "fields": []},
            {"id": "new", "fields": []},
        ]
        with (
            patch.object(RECONCILER, "kustomizations_ready", return_value=True),
            patch.object(RECONCILER, "is_dry_run", return_value=False),
            patch.object(
                RECONCILER, "discover_items", return_value={"App": item_configuration()}
            ),
            patch.object(RECONCILER, "connect", side_effect=replies) as connect,
        ):
            with self.assertRaisesRegex(RuntimeError, "original retained"):
                RECONCILER.main()
        self.assertNotIn(
            "DELETE", [call.kwargs.get("method") for call in connect.call_args_list]
        )

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
            patch.object(RECONCILER, "kustomizations_ready", return_value=True),
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
        ):
            with self.assertRaisesRegex(RuntimeError, "duplicate 1Password item title"):
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
            "kustomizations_ready": RECONCILER.kustomizations_ready,
            "connect": RECONCILER.connect,
            "discover_items": RECONCILER.discover_items,
            "is_dry_run": RECONCILER.is_dry_run,
        }
        for name, value in originals.items():
            self.addCleanup(setattr, RECONCILER, name, value)
        RECONCILER.kustomizations_ready = lambda: False
        RECONCILER.connect = connect
        RECONCILER.discover_items = lambda cluster=None: {"Pocket ID": desired}
        RECONCILER.is_dry_run = lambda: False
        with contextlib.redirect_stdout(io.StringIO()):
            RECONCILER.main()
        self.assertFalse(
            any(method in {"DELETE", "POST", "PUT"} for method, _, _ in calls)
        )

    def test_kustomizations_ready_require_every_current_ready_condition(self):
        def kustomization(source):
            return {
                "metadata": {"generation": 3, "namespace": "flux-system"},
                "spec": {"sourceRef": {"kind": "GitRepository", "name": source}},
                "status": {
                    "conditions": [{"status": "True", "type": "Ready"}],
                    "lastAppliedRevision": f"{source}@sha1:current",
                    "observedGeneration": 3,
                },
            }

        applications, mini_apps = kustomization("flux-system"), kustomization("mini-apps")
        sources = {
            name: {"status": {"artifact": {"revision": f"{name}@sha1:current"}}}
            for name in ["flux-system", "mini-apps"]
        }
        with (
            patch.object(
                RECONCILER,
                "kubernetes_list",
                side_effect=lambda path: [applications, mini_apps],
            ),
            patch.object(
                RECONCILER,
                "kubernetes_get",
                side_effect=lambda path: sources[path.rsplit("/", 1)[-1]],
            ),
        ):
            self.assertTrue(RECONCILER.kustomizations_ready())
            for resource in [mini_apps, sources["mini-apps"]]:
                resource.setdefault("spec", {})["suspend"] = True
                self.assertFalse(RECONCILER.kustomizations_ready())
                resource["spec"]["suspend"] = False
            sources["mini-apps"]["status"]["artifact"]["revision"] = "mini-apps@sha1:new"
            self.assertFalse(RECONCILER.kustomizations_ready())
            sources["mini-apps"]["status"]["artifact"]["revision"] = "mini-apps@sha1:current"
            mini_apps["status"]["observedGeneration"] = 2
            self.assertFalse(RECONCILER.kustomizations_ready())
            mini_apps["status"]["observedGeneration"] = 3
            mini_apps["spec"]["sourceRef"]["kind"] = "OCIRepository"
            self.assertFalse(RECONCILER.kustomizations_ready())

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
        self.assertEqual(desired["Comfy Control"]["namespaces"], {"comfy-control"})
        self.assertEqual(desired["Comfy Control"]["urls"], {"https://comfy.excloo.com"})
        self.assertTrue(desired["Comfy Control"]["login"])
        self.assertEqual(desired["CLIProxyAPI"]["namespaces"], set())
        self.assertFalse(desired["CLIProxyAPI"]["login"])

    def test_discovery_recognises_data_from_extract_owner(self):
        resources = [
            {
                "kind": "ExternalSecret",
                "metadata": {
                    "annotations": {
                        "onepassword.excloo.dev/defaults": '{"widget-key":""}',
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
        self.assertEqual(desired["Homepage"]["namespaces"], {"homepage"})
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
        self.assertEqual(desired["Headlamp"]["namespaces"], {"headlamp"})
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
                    "onepassword.excloo.dev/url": "https://headlamp.example.net/login",
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
        self.assertEqual(
            desired["Headlamp"]["urls"],
            {
                "https://headlamp.example.net",
                "https://headlamp.example.net/login",
            },
        )

    def test_secret_can_explicitly_share_another_items_login(self):
        secret = {
            "kind": "ExternalSecret",
            "metadata": {
                "annotations": {"onepassword.excloo.dev/login-item": "Dashboard"},
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
        with patch.object(
            RECONCILER,
            "kubernetes_list",
            side_effect=lambda path: [route] if "httproutes" in path else [],
        ):
            with self.assertRaisesRegex(RuntimeError, "has no URL"):
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
            "kustomizations_ready": RECONCILER.kustomizations_ready,
            "connect": RECONCILER.connect,
            "discover_items": RECONCILER.discover_items,
            "is_dry_run": RECONCILER.is_dry_run,
        }
        for name, value in originals.items():
            self.addCleanup(setattr, RECONCILER, name, value)
        RECONCILER.kustomizations_ready = lambda: False
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
