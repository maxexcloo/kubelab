"""Delivery must reject stale readiness and superseding revisions."""

import importlib.util
import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "deploy", Path(__file__).resolve().parents[1] / "scripts/deploy.py"
)
deploy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(deploy)
REVISION = "a" * 40


def release(generation=2, observed=2):
    return {
        "metadata": {"generation": generation},
        "status": {
            "observedGeneration": observed,
            "conditions": [{"type": "Ready", "status": "True"}],
            "history": [{"name": "release"}],
        },
    }


class DeliveryTests(unittest.TestCase):
    def test_stale_or_reconciling_ready_is_rejected(self):
        self.assertFalse(deploy.ready(release(observed=1)))
        for condition in ("Reconciling", "Stalled"):
            resource = release()
            resource["status"]["conditions"].append({"type": condition, "status": "True"})
            self.assertFalse(deploy.ready(resource))
        self.assertTrue(deploy.ready(release()))

    def verify(self, source_revision=REVISION, applied_revision=REVISION, final_generation=2):
        responses = [
            {"status": {"artifact": {"revision": f"main@sha1:{source_revision}"}}},
            {"status": {"lastAppliedRevision": f"main@sha1:{applied_revision}"}},
            release(),
            {"items": [
                {"kind": "Deployment", "metadata": {
                    "name": "owned", "annotations": {"meta.helm.sh/release-name": "release"}
                }},
                {"kind": "Deployment", "metadata": {
                    "name": "unrelated", "annotations": {"meta.helm.sh/release-name": "another"}
                }},
            ]},
            {"status": {"artifact": {"revision": f"main@sha1:{REVISION}"}}},
            release(generation=final_generation, observed=final_generation),
        ]
        with patch.object(deploy, "run", side_effect=[json.dumps(item) for item in responses]):
            deploy.deploy("cluster", "namespace/release", REVISION)

    @patch.object(subprocess, "run")
    def test_only_touched_release_rollout_is_verified(self, command):
        self.verify()
        rollouts = [call.args[0] for call in command.call_args_list if "rollout" in call.args[0]]
        self.assertEqual(len(rollouts), 1)
        self.assertIn("deployment/owned", rollouts[0])
        self.assertIn("namespace", rollouts[0])

    @patch.object(subprocess, "run")
    def test_superseded_or_unapplied_revision_is_rejected(self, _command):
        for key in ("source_revision", "applied_revision"):
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                self.verify(**{key: "b" * 40})

    @patch.object(subprocess, "run")
    def test_concurrent_application_change_is_rejected(self, _command):
        with self.assertRaisesRegex(RuntimeError, "changed during verification"):
            self.verify(final_generation=3)


if __name__ == "__main__":
    unittest.main()
