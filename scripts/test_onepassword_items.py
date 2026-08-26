#!/usr/bin/env python3

import contextlib
import io
import subprocess
import types
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
RECONCILER_MANIFEST = (
    REPOSITORY_ROOT / "platform/secrets/onepassword-items/reconciler.yaml"
)


def load_reconciler():
    result = subprocess.run(
        [
            "yq",
            "-r",
            'select(.kind == "ConfigMap" and .metadata.name == "onepassword-items") '
            '| .data."reconcile.py"',
            RECONCILER_MANIFEST,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    module = types.ModuleType("onepassword_items")
    exec(compile(result.stdout, RECONCILER_MANIFEST, "exec"), module.__dict__)
    return module


RECONCILER = load_reconciler()


def item_configuration(**overrides):
    configuration = {
        "adopt": set(),
        "constants": {},
        "defaults": {},
        "fields": set(),
        "generate": set(),
        "login": False,
        "migrate": {},
        "namespaces": set(),
        "remove": set(),
        "urls": set(),
    }
    configuration.update(overrides)
    return configuration


class ReconcilerTests(unittest.TestCase):
    def test_adoption_migrates_legacy_fields_without_archiving_the_item(self):
        legacy = {
            "category": "LOGIN",
            "fields": [
                {"id": "encryption_key", "label": "encryption_key", "value": "preserve-me"},
            ],
            "id": "legacy-id",
            "sections": [],
            "tags": ["Homelab"],
            "title": "Excloo ID (pocket-id)",
        }
        calls = []

        def connect(path, *, body=None, method="GET"):
            calls.append((method, path, body))
            if path == "/vaults":
                return [{"id": "vault"}]
            if path == "/vaults/vault/items":
                return [{"id": "legacy-id", "title": legacy["title"]}]
            if path == "/vaults/vault/items/legacy-id" and method == "GET":
                return dict(legacy)
            if path == "/vaults/vault/items/legacy-id" and method == "PUT":
                return body
            self.fail(f"unexpected Connect request: {method} {path}")

        desired = item_configuration(
            adopt={legacy["title"]},
            fields={"encryption-key"},
            login=True,
            migrate={"encryption_key": "encryption-key"},
            remove={"encryption_key"},
            urls={"https://id.excloo.com"},
        )
        originals = {
            "applications_ready": RECONCILER.applications_ready,
            "connect": RECONCILER.connect,
            "discover_items": RECONCILER.discover_items,
            "is_dry_run": RECONCILER.is_dry_run,
        }
        for name, value in originals.items():
            self.addCleanup(setattr, RECONCILER, name, value)
        RECONCILER.applications_ready = lambda: True
        RECONCILER.connect = connect
        RECONCILER.discover_items = lambda: {"Excloo ID": desired}
        RECONCILER.is_dry_run = lambda: False
        with contextlib.redirect_stdout(io.StringIO()):
            RECONCILER.main()
        updates = [body for method, _, body in calls if method == "PUT"]
        self.assertEqual(len(updates), 1)
        fields = {field["label"]: field for field in updates[0]["fields"]}
        self.assertEqual(updates[0]["title"], "Excloo ID")
        self.assertEqual(fields["encryption-key"]["value"], "preserve-me")
        self.assertNotIn("encryption_key", fields)
        self.assertFalse(any(method == "DELETE" for method, _, _ in calls))

    def test_applications_ready_requires_current_ready_condition(self):
        application = {
            "metadata": {"generation": 3, "namespace": "flux-system"},
            "spec": {
                "sourceRef": {
                    "kind": "GitRepository",
                    "name": "flux-system",
                }
            },
            "status": {
                "conditions": [{"status": "True", "type": "Ready"}],
                "lastAppliedRevision": "main@sha1:current",
                "observedGeneration": 3,
            },
        }
        source = {
            "status": {"artifact": {"revision": "main@sha1:current"}},
        }
        original = RECONCILER.kubernetes_get
        self.addCleanup(setattr, RECONCILER, "kubernetes_get", original)
        RECONCILER.kubernetes_get = (
            lambda path: source if "gitrepositories" in path else application
        )
        self.assertTrue(RECONCILER.applications_ready())
        source["status"]["artifact"]["revision"] = "main@sha1:new"
        self.assertFalse(RECONCILER.applications_ready())
        source["status"]["artifact"]["revision"] = "main@sha1:current"
        application["status"]["observedGeneration"] = 2
        self.assertFalse(RECONCILER.applications_ready())

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
            "applications_ready": RECONCILER.applications_ready,
            "connect": RECONCILER.connect,
            "discover_items": RECONCILER.discover_items,
            "is_dry_run": RECONCILER.is_dry_run,
        }
        for name, value in originals.items():
            self.addCleanup(setattr, RECONCILER, name, value)
        RECONCILER.applications_ready = lambda: False
        RECONCILER.connect = connect
        RECONCILER.discover_items = lambda: {}
        RECONCILER.is_dry_run = lambda: False
        with contextlib.redirect_stdout(io.StringIO()):
            RECONCILER.main()
        self.assertFalse(any(method == "DELETE" for method, _, _ in calls))

    def test_migration_preserves_legacy_source_for_rollback(self):
        current = {
            "category": "LOGIN",
            "fields": [
                {"id": "secret_key", "label": "secret_key", "value": "preserve-me"},
            ],
            "sections": [],
        }
        desired = item_configuration(
            fields={"secret-key"},
            login=True,
            migrate={"secret_key": "secret-key"},
            urls={"https://application.excloo.com"},
        )
        result = RECONCILER.normalise_item(current, "Application", desired, "vault")
        fields = {field["label"]: field for field in result["fields"]}
        self.assertEqual(fields["secret-key"]["value"], "preserve-me")
        self.assertEqual(fields["secret_key"]["value"], "preserve-me")

    def test_normalisation_preserves_values_and_orders_login_fields(self):
        current = {
            "category": "SERVER",
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
        self.assertEqual(result["tags"], ["Kubelab"])
        self.assertEqual(result["urls"], [{"href": "https://application.excloo.com", "primary": True}])
        self.assertEqual(fields["password"]["value"], "edited")
        self.assertEqual(fields["token"]["value"], "preserved")
        self.assertEqual(fields["username"]["value"], "admin")
        self.assertEqual(fields["database-username"]["value"], "application")
        self.assertTrue(fields["api-key"]["generate"])
        self.assertEqual(
            [field["label"] for field in result["fields"]],
            [
                "username",
                "password",
                "database-username",
                "database-password",
                "api-key",
                "token",
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
