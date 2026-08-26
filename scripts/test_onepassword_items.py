#!/usr/bin/env python3

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
                        "onepassword.excloo.dev/login": "true",
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
                "metadata": {"name": "comfy-control", "namespace": "comfy-control"},
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

    def test_homelab_tag_defines_external_ownership(self):
        self.assertTrue(RECONCILER.externally_owned({"tags": ["Homelab"]}))
        self.assertFalse(RECONCILER.externally_owned({"tags": ["Kubelab"]}))

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


if __name__ == "__main__":
    unittest.main()
