#!/usr/bin/env python3

import json
import subprocess
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent


def rendered_resources(path):
    manifests = subprocess.run(
        ["kustomize", "build", path],
        check=True,
        capture_output=True,
        cwd=REPOSITORY_ROOT,
        text=True,
    ).stdout
    resources = subprocess.run(
        ["yq", "eval-all", "-o=json", "-I=0", "[select(.kind != null)]", "-"],
        check=True,
        capture_output=True,
        cwd=REPOSITORY_ROOT,
        input=manifests,
        text=True,
    ).stdout
    return json.loads(resources)


def identity(resource):
    metadata = resource["metadata"]
    return (
        resource["apiVersion"],
        resource["kind"],
        metadata.get("namespace", ""),
        metadata["name"],
    )


class InventoryTransferTests(unittest.TestCase):
    def test_onepassword_new_owner_precedes_old_owner_pruning(self):
        for cluster in ("mbk", "syd"):
            reconciliations = {
                resource["metadata"]["name"]: resource
                for resource in rendered_resources(f"clusters/{cluster}")
                if resource["kind"] == "Kustomization"
                and resource["metadata"].get("namespace") == "flux-system"
            }
            foundation = {
                identity(resource): resource
                for resource in rendered_resources(f"clusters/{cluster}/foundation")
            }
            platform = {
                identity(resource): resource
                for resource in rendered_resources(f"clusters/{cluster}/platform")
            }
            transferred = {
                (
                    "helm.toolkit.fluxcd.io/v2",
                    "HelmRelease",
                    "external-secrets",
                    "onepassword-connect",
                ),
                (
                    "source.toolkit.fluxcd.io/v1",
                    "HelmRepository",
                    "flux-system",
                    "onepassword",
                ),
            }
            self.assertTrue(transferred <= set(foundation))
            self.assertTrue(transferred.isdisjoint(platform))
            for resource_id in transferred:
                annotations = foundation[resource_id]["metadata"]["annotations"]
                self.assertEqual(
                    annotations["kustomize.toolkit.fluxcd.io/prune"], "disabled"
                )
                self.assertNotIn("kustomize.toolkit.fluxcd.io/ssa", annotations)
            self.assertEqual(
                reconciliations["platform"]["spec"]["dependsOn"],
                [{"name": "foundation"}],
            )

    def test_victoria_metrics_bridge_is_non_mutating_and_bootstrap_safe(self):
        for cluster in ("mbk", "syd"):
            expected = {
                identity(resource): resource
                for resource in rendered_resources(
                    f"clusters/{cluster}/platform/observability/victoria-metrics/base"
                )
            }
            foundation = {
                identity(resource): resource
                for resource in rendered_resources(f"clusters/{cluster}/foundation")
            }
            platform = {
                identity(resource): resource
                for resource in rendered_resources(f"clusters/{cluster}/platform")
            }
            self.assertTrue(set(expected) <= set(foundation))
            self.assertTrue(set(expected) <= set(platform))
            release_id = next(
                resource_id
                for resource_id in expected
                if resource_id[1] == "HelmRelease"
            )
            for resource_id, resource in expected.items():
                annotations = resource["metadata"]["annotations"]
                self.assertEqual(
                    annotations["kustomize.toolkit.fluxcd.io/prune"], "disabled"
                )
                foundation_resource = foundation[resource_id]
                self.assertEqual(
                    foundation_resource["metadata"]["annotations"][
                        "kustomize.toolkit.fluxcd.io/ssa"
                    ],
                    "IfNotPresent",
                )
                if resource_id != release_id:
                    platform_resource = platform[resource_id]
                    self.assertEqual(platform_resource, resource)

            foundation_release = foundation[release_id]
            self.assertEqual(
                foundation_release["spec"]["dependsOn"],
                [{"name": "local-path-provisioner", "namespace": "storage"}],
            )
            for action in ("install", "upgrade"):
                self.assertEqual(
                    foundation_release["spec"][action]["remediation"]["retries"], 3
                )
            self.assertNotIn("admin", foundation_release["spec"]["values"]["grafana"])
            platform_release = platform[release_id]
            self.assertEqual(
                {dependency["name"] for dependency in platform_release["spec"]["dependsOn"]},
                {"external-secrets", "local-path-provisioner", "onepassword-connect"},
            )
            for action in ("install", "upgrade"):
                self.assertEqual(
                    platform_release["spec"][action]["remediation"]["retries"], 3
                )
            self.assertEqual(
                platform_release["spec"]["values"]["grafana"]["admin"][
                    "existingSecret"
                ],
                "grafana",
            )
            foundation_grafana_secrets = [
                resource
                for resource in foundation.values()
                if resource["kind"] == "ExternalSecret"
                and resource["metadata"]["name"] == "grafana"
            ]
            platform_grafana_secrets = [
                resource
                for resource in platform.values()
                if resource["kind"] == "ExternalSecret"
                and resource["metadata"]["name"] == "grafana"
            ]
            self.assertEqual(foundation_grafana_secrets, [])
            self.assertEqual(len(platform_grafana_secrets), 1)


if __name__ == "__main__":
    unittest.main()
