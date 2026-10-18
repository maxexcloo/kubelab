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
                                        "tag": "v1.2.3",
                                    }
                                }
                            }
                        }
                    }
                }
            },
        }
        (manifest,) = updates.manifests("apps/new.yaml", document)
        source = manifest["sources"]["version"]["spec"]
        self.assertEqual(source["image"], "registry.invalid:5000/app")
        self.assertEqual(source["tagfilter"], r"^v([0-9]+(?:\.[0-9]+)(?:\.[0-9]+))$")
        self.assertEqual(
            manifest["targets"]["image"]["spec"]["key"],
            "$.spec.values.controllers.new.containers.app.image.tag",
        )

    def test_variants_keep_their_suffix(self):
        manifest = updates.image_manifest(
            "app.yaml", "$.image.tag", "example/app", "26.7.0-rootless"
        )
        self.assertEqual(
            manifest["sources"]["version"]["spec"]["tagfilter"],
            r"^([0-9]+(?:\.[0-9]+)(?:\.[0-9]+))\-rootless$",
        )

    def test_database_images_keep_their_major_version(self):
        document = {
            "kind": "Cluster",
            "spec": {
                "imageName": "registry.invalid:5000/postgres:18.6-standard-trixie",
                "extensions": [{"reference": "registry.invalid/extension:pg18-v1.1.1"}],
            },
        }
        (manifest,) = updates.manifests("apps/database.yaml", document)
        self.assertEqual(
            manifest["sources"]["version"]["spec"]["image"],
            "registry.invalid:5000/postgres",
        )
        self.assertEqual(
            manifest["sources"]["version"]["spec"]["tagfilter"],
            r"^(18(?:\.[0-9]+))\-standard\-trixie$",
        )
        self.assertEqual(
            manifest["targets"]["image"]["transformers"],
            [{"addprefix": "registry.invalid:5000/postgres:"}],
        )

    def test_unversioned_tags_have_no_policy(self):
        for tag in ("latest", "sha-123", "stable-rocm"):
            with self.subTest(tag=tag):
                self.assertIsNone(
                    updates.image_manifest("app.yaml", "$.image.tag", "example/app", tag)
                )

    def test_generated_yaml_can_be_templated_by_updatecli(self):
        manifest = updates.image_manifest(
            "app.yaml", "$.image.tag", "example/app", "1.2.3"
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
