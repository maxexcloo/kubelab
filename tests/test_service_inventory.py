"""Check inventory reuse and validation against rendered manifests."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


class ServiceInventoryTests(unittest.TestCase):
    def test_snapshot_is_rendered_once_and_reused_by_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            manifests = temporary / "manifests"
            commands = temporary / "bin"
            commands.mkdir()
            log = temporary / "builds"
            wrapper = commands / "kustomize"
            wrapper.write_text(
                '#!/bin/sh\nprintf "%s\\n" "$*" >> "$BUILD_LOG"\n'
                'exec "$REAL_KUSTOMIZE" "$@"\n'
            )
            wrapper.chmod(0o755)
            env = dict(
                os.environ,
                HOMELAB_DIRECTORY=str(ROOT / "tests/fixtures/homepage/homelab"),
                BUILD_LOG=str(log),
                PATH=f"{commands}:{os.environ['PATH']}",
                REAL_KUSTOMIZE=shutil.which("kustomize"),
            )
            subprocess.run(
                ["scripts/render_manifests.sh", str(manifests)],
                cwd=ROOT, env=env, check=True,
            )
            builds = log.read_text().splitlines()
            self.assertTrue(builds)
            self.assertEqual(len(builds), len(set(builds)))
            for cluster in ("mbk", "syd"):
                self.assertIn(f"build clusters/{cluster}", builds)
                self.assertIn(f"build apps/overlays/{cluster}", builds)

            for options in ([], ["--all-routes"], ["--include-static"], ["syd"]):
                command = ["scripts/render_service_inventory.sh", *options]
                expected = subprocess.check_output(
                    command, cwd=ROOT,
                    env=dict(os.environ, HOMELAB_DIRECTORY=env["HOMELAB_DIRECTORY"]),
                )
                actual = subprocess.check_output(
                    [*command, "--manifest-directory", str(manifests)],
                    cwd=ROOT, env=env,
                )
                self.assertEqual(json.loads(actual), json.loads(expected))
                redlib = [entry for entry in json.loads(actual) if entry["name"] == "Redlib"]
                self.assertEqual(len(redlib), 1)
                self.assertEqual(redlib[0]["alerts"], "false")
            subprocess.run(
                ["scripts/check_service_metadata.sh", str(manifests)],
                cwd=ROOT, env=env, check=True,
            )
            self.assertEqual(log.read_text().splitlines(), builds)

            # Dashboard visibility must not change external monitoring membership.
            original_inventory = subprocess.check_output(
                ["scripts/render_service_inventory.sh", "--manifest-directory", str(manifests)],
                cwd=ROOT, env=env,
            )
            for path in manifests.rglob("*.yaml"):
                subprocess.run(["yq", "-i", '(.. | select(tag == "!!map" and has("gethomepage.dev/enabled")))."gethomepage.dev/enabled" = "false"', str(path)], check=True)
            hidden_inventory = subprocess.check_output(
                ["scripts/render_service_inventory.sh", "--manifest-directory", str(manifests)],
                cwd=ROOT, env=env,
            )
            self.assertEqual(json.loads(original_inventory), json.loads(hidden_inventory))

            # A broken access label in the snapshot must still fail validation.
            source = manifests / "apps/overlays/mbk.yaml"
            subprocess.run(
                ["yq", "-i", 'del(.metadata.labels."gateway.excloo.dev/public-access")', str(source)],
                check=True,
            )
            result = subprocess.run(
                ["scripts/check_service_metadata.sh", str(manifests)],
                cwd=ROOT, env=env, capture_output=True, text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("public-access label", result.stderr)
            self.assertEqual(log.read_text().splitlines(), builds)
