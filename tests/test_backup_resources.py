"""S3 backups cover app state and databases without retired NFS backup volumes."""

import unittest

from support import repository_resources


class BackupResourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.resources = repository_resources("apps/overlays/syd")

    def test_database_identities_and_backup_references_follow_the_app_namespace(self):
        databases = {
            (item["metadata"]["namespace"], item["metadata"]["name"]): item
            for item in self.resources if item["kind"] == "Cluster"
        }
        self.assertTrue(databases)
        for (namespace, name), database in databases.items():
            with self.subTest(namespace=namespace):
                self.assertEqual(name, namespace + "-database")
                self.assertEqual(database["spec"]["bootstrap"]["initdb"], {
                    "database": namespace, "owner": namespace, "secret": {"name": name},
                })
        for item in self.resources:
            if item["kind"] == "ScheduledBackup":
                self.assertIn((item["metadata"]["namespace"], item["spec"]["cluster"]["name"]), databases)

    def test_hdd_backup_jobs_and_claims_are_absent(self):
        for item in self.resources:
            if item["kind"] == "CronJob":
                self.assertNotIn(item["metadata"]["name"], ["file-backup", "postgres-backup"])
            if item["kind"] == "PersistentVolumeClaim":
                self.assertNotEqual(item["metadata"]["name"], "backups")
                self.assertNotEqual(item["spec"].get("storageClassName"), "local-backups")

    def test_s3_backups_cover_databases_and_exclude_bulk_media(self):
        stores = [item for item in self.resources if item["kind"] == "ObjectStore"]
        self.assertEqual(len(stores), 7)
        for item in stores:
            self.assertEqual(item["spec"]["retentionPolicy"], "14d")
            self.assertEqual(item["spec"]["configuration"]["endpointURL"], "https://kimbap.mbk.excloo.net:9000")
        jobs = [item for item in self.resources if item["kind"] == "CronJob" and item["metadata"]["name"] == "state-backup"]
        namespaces = {item["metadata"]["namespace"] for item in jobs}
        self.assertIn("redlib-multi", namespaces)
        self.assertFalse(namespaces & {"bichon", "romm"})
        for item in jobs:
            spec = item["spec"]
            self.assertEqual(spec["timeZone"], "Australia/Sydney")
            claims = [v["persistentVolumeClaim"]["claimName"] for v in spec["jobTemplate"]["spec"]["template"]["spec"]["volumes"] if "persistentVolumeClaim" in v]
            self.assertFalse(set(claims) & {"books", "games", "icloud-photos", "library", "immich-machine-learning", "retained-data"})
        for item in self.resources:
            if item["kind"] == "Role" and item["metadata"]["name"] == "state-backup":
                for rule in item["rules"]:
                    self.assertNotIn("secrets", rule["resources"])
                    if "deployments/scale" in rule["resources"]:
                        self.assertEqual(rule["resourceNames"], [item["metadata"]["namespace"]])

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
