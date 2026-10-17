"""Dependency discovery preserves compatibility and follows owning manifests."""

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "updates", Path(__file__).resolve().parents[1] / "scripts/updates.py"
)
updates = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(updates)


class UpdateDiscoveryTests(unittest.TestCase):
    def test_shared_images_target_anchor_definitions_only(self):
        manifests = list(updates.discover())
        for application, definition, alias in (
            (
                "sidestore-vpn",
                "$.spec.values.controllers.main.initContainers.forwarding.image.tag",
                "$.spec.values.controllers.main.containers.tailscale.image.tag",
            ),
            (
                "syncthing",
                "$.spec.values.controllers.main.containers.main.image.tag",
                "$.spec.values.controllers.main.initContainers.authentication.image.tag",
            ),
        ):
            with self.subTest(application=application):
                keys = [
                    manifest["targets"]["image"]["spec"]["key"]
                    for manifest in manifests
                    if manifest["targets"]["image"]["spec"]["file"]
                    == f"apps/base/{application}/helm-release.yaml"
                ]
                self.assertEqual(keys.count(definition), 1)
                self.assertNotIn(alias, keys)

    def test_new_images_are_discovered_without_a_policy_list(self):
        document = {
            "kind": "HelmRelease",
            "spec": {
                "values": {
                    "controllers": {
                        "new": {
                            "containers": {
                                "app": {
                                    "image": {
                                        "repository": "registry.invalid:5000/app",
                                        "tag": "1.2.3@sha256:old",
                                    }
                                }
                            }
                        }
                    }
                }
            },
        }
        (manifest,) = updates.manifests("apps/new.yaml", document)
        self.assertEqual(
            manifest["sources"]["version"]["spec"]["image"], "registry.invalid:5000/app"
        )
        self.assertEqual(
            manifest["targets"]["image"]["spec"]["key"],
            "$.spec.values.controllers.new.containers.app.image.tag",
        )
        self.assertEqual(
            manifest["sources"]["digest"]["transformers"],
            [{"find": r"sha256:[a-f0-9]{64}$"}],
        )
        self.assertEqual(
            manifest["sources"]["digest"]["spec"]["tag"], '{{ source "version" }}'
        )

    def test_database_versions_and_source_variants_remain_fixed(self):
        document = {
            "kind": "Cluster",
            "spec": {
                "imageName": "registry.invalid:5000/postgres:18.6-standard@sha256:old",
                "extensions": [
                    {"reference": "registry.invalid/extension:pg18-v1.1.1@sha256:old"}
                ],
            },
        }
        manifests = list(updates.manifests("apps/database.yaml", document))
        self.assertEqual(len(manifests), 2)
        for manifest in manifests:
            self.assertNotIn("version", manifest["sources"])
        self.assertEqual(
            manifests[0]["sources"]["digest"]["spec"]["image"],
            "registry.invalid:5000/postgres",
        )
        self.assertEqual(
            manifests[1]["targets"]["image"]["spec"]["key"],
            "$.spec.extensions[0].reference",
        )
        manifest = updates.image_manifest(
            "app.yaml", "$.image.tag", "example/app", "sha-123@sha256:old"
        )
        self.assertEqual(manifest["sources"]["digest"]["spec"]["tag"], "sha-123")

    def test_undigested_variant_is_not_switched_to_another_release(self):
        self.assertIsNone(
            updates.image_manifest(
                "app.yaml", "$.image.tag", "example/app", "stable-rocm"
            )
        )

    def test_generated_yaml_can_be_templated_by_updatecli(self):
        manifest = updates.image_manifest(
            "app.yaml", "$.image.tag", "example/app", "1.2.3@sha256:old"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "image.yaml"
            updates.write_manifest(path, manifest)
            result = subprocess.run(
                [
                    "updatecli",
                    "manifest",
                    "show",
                    "--config",
                    str(path),
                    "--disable-prepare",
                    "--unique-tmp-dir",
                ],
                capture_output=True,
                check=False,
                text=True,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
