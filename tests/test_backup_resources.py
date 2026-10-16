"""Applications retain state and database isolation without retired HDD backups."""

import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class BackupResourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rendered = subprocess.check_output(
            ["kubectl", "kustomize", str(ROOT / "apps/overlays/syd")], text=True
        )
        documents = subprocess.check_output(
            ["yq", "-I=0", "-o=json", "."], input=rendered, text=True
        )
        cls.resources = [item for item in map(json.loads, documents.splitlines()) if item]

    def test_hdd_backup_jobs_and_claims_are_absent(self):
        for item in self.resources:
            if item["kind"] == "CronJob":
                self.assertNotIn(item["metadata"]["name"], ["file-backup", "postgres-backup"])
            if item["kind"] == "PersistentVolumeClaim":
                self.assertNotEqual(item["metadata"]["name"], "backups")
                self.assertNotEqual(item["spec"].get("storageClassName"), "local-backups")

    def test_application_state_and_database_isolation_remain(self):
        claims = [item for item in self.resources if item["kind"] == "PersistentVolumeClaim"]
        self.assertTrue(claims)
        self.assertTrue(all(item["spec"]["storageClassName"] in ["", "local-path", "atvloadly-local"] for item in claims))
        policies = {(item["metadata"]["namespace"], item["metadata"]["name"])
                    for item in self.resources if item["kind"] == "NetworkPolicy"}
        for namespace in ["bookorbit", "immich", "linkwarden", "miniflux", "pocket-id", "romm"]:
            self.assertIn((namespace, namespace + "-database"), policies)
        self.assertNotIn(("litellm", "postgres-backup"), policies)


if __name__ == "__main__":
    unittest.main()
