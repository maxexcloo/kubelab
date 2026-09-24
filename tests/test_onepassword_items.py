#!/usr/bin/env python3

"""Tests for the 1Password item reconciler."""

import contextlib
import importlib.util
import io
import unittest
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
        "generate": set(),
        "login": False,
        "namespaces": set(),
        "urls": set(),
    }
    configuration.update(overrides)
    return configuration


class ReconcilerTests(unittest.TestCase):
    def test_duplicate_titles_stop_before_any_item_changes(self):
        summaries = [
            {"id": "first", "title": "Application"},
            {"id": "second", "title": "Application"},
        ]
        with patch.object(RECONCILER, "discover_items", return_value={}), patch.object(
            RECONCILER, "connect", side_effect=[[{"id": "vault"}], summaries]
        ) as connect:
            with self.assertRaisesRegex(RuntimeError, "duplicate 1Password item title"):
                RECONCILER.main()
        self.assertEqual(connect.call_count, 2)

    def test_route_changes_do_not_replace_existing_items(self):
        current = {
            "category": "SERVER", "id": "stable-id", "fields": [],
            "sections": [], "tags": ["Kubelab"], "title": "Application",
            "urls": [], "vault": {"id": "vault"},
        }
        with patch.object(
            RECONCILER, "discover_items",
            return_value={"Application": item_configuration(login=True, urls={"https://new.example.com"})},
        ), patch.object(RECONCILER, "connect", side_effect=[
            [{"id": "vault"}], [{"id": "stable-id", "title": "Application"}], current,
        ]) as connect, contextlib.redirect_stdout(io.StringIO()):
            RECONCILER.main()
        self.assertEqual(connect.call_count, 3)

    def test_main_leaves_externally_owned_existing_item_unchanged(self):
        existing = {
            "category": "LOGIN",
            "fields": [
                {"id": "password", "label": "password", "value": "preserve-me"},
            ],
            "id": "existing-id",
            "sections": [],
            "tags": ["Homelab"],
            "title": "Excloo ID",
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
            "connect": RECONCILER.connect,
            "discover_items": RECONCILER.discover_items,
            "is_dry_run": RECONCILER.is_dry_run,
        }
        for name, value in originals.items():
            self.addCleanup(setattr, RECONCILER, name, value)
        RECONCILER.connect = connect
        RECONCILER.discover_items = lambda: {"Excloo ID": desired}
        RECONCILER.is_dry_run = lambda: False
        with contextlib.redirect_stdout(io.StringIO()):
            RECONCILER.main()
        self.assertFalse(any(method in {"DELETE", "POST", "PUT"} for method, _, _ in calls))

    def test_discovery_infers_owner_and_route_without_title_annotation(self):
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
                        "gethomepage.dev/name": "Comfy Control",
                    },
                    "name": "comfy-control",
                    "namespace": "comfy-control",
                },
                "spec": {"hostnames": ["comfy.excloo.com"]},
            }
        ]
        original = RECONCILER.kubernetes_list
        self.addCleanup(setattr, RECONCILER, "kubernetes_list", original)
        RECONCILER.kubernetes_list = lambda path: routes if "httproutes" in path else resources
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
        RECONCILER.kubernetes_list = lambda path: [] if "httproutes" in path else resources
        desired = RECONCILER.discover_items()
        self.assertEqual(set(desired), {"Homepage"})
        self.assertEqual(desired["Homepage"]["defaults"], {"widget-key": ""})
        self.assertEqual(desired["Homepage"]["namespaces"], {"homepage"})
        self.assertFalse(desired["Homepage"]["login"])

    def test_discovery_seeds_only_homepage_routes(self):
        routes = [
            {
                "metadata": {
                    "annotations": {
                        "gethomepage.dev/enabled": "true",
                        "gethomepage.dev/href": "https://headlamp.mbk.excloo.dev",
                        "gethomepage.dev/name": "Headlamp",
                    },
                    "name": "headlamp",
                    "namespace": "headlamp",
                },
                "spec": {"hostnames": ["headlamp.mbk.excloo.dev"]},
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
            {"https://headlamp.mbk.excloo.dev"},
        )

    def test_homelab_tag_defines_external_ownership(self):
        self.assertTrue(RECONCILER.externally_owned({"tags": ["Homelab"]}))
        self.assertFalse(RECONCILER.externally_owned({"tags": ["Kubelab"]}))

    def test_main_leaves_unreferenced_items_untouched(self):
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
            "connect": RECONCILER.connect,
            "discover_items": RECONCILER.discover_items,
            "is_dry_run": RECONCILER.is_dry_run,
        }
        for name, value in originals.items():
            self.addCleanup(setattr, RECONCILER, name, value)
        RECONCILER.connect = connect
        RECONCILER.discover_items = lambda: {}
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
        self.assertEqual(result["category"], "SERVER")
        self.assertEqual(result["id"], "existing-id")
        self.assertEqual(result["tags"], ["Kubelab", "Personal"])
        self.assertEqual(result["urls"], [{"href": "https://old.example.com", "primary": True}])
        self.assertEqual(fields["password"]["value"], "edited")
        self.assertEqual(fields["token"]["value"], "preserved")
        self.assertEqual(fields["username"]["value"], "admin")
        self.assertEqual(fields["database-username"]["value"], "application")
        self.assertTrue(fields["api-key"]["generate"])
        self.assertEqual(
            [field["label"] for field in result["fields"]],
            [
                "password",
                "token",
                "api-key",
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
