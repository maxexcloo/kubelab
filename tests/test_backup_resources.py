"""Backup jobs must resolve app-owned credentials, scripts and source permissions."""

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
            ["yq", "-I=0", "-N", "-o=json", "."], input=rendered, text=True
        )
        cls.resources = {
            (item["kind"], item["metadata"].get("namespace"), item["metadata"]["name"]): item
            for item in map(json.loads, documents.splitlines())
        }

    def test_backup_storage_uses_the_direct_hdd_dataset(self):
        rendered = subprocess.check_output(
            ["kubectl", "kustomize", str(ROOT / "platform/foundation")], text=True
        )
        documents = subprocess.check_output(
            ["yq", "-I=0", "-N", "-o=json", "."], input=rendered, text=True
        )
        releases = {item["metadata"]["name"]: item for item in
                    map(json.loads, documents.splitlines()) if item["kind"] == "HelmRelease"}
        classes = releases["local-path-provisioner"]["spec"]["values"]["storageClassConfigs"]
        backups = classes["local-backups"]
        self.assertEqual(backups["nodePathMap"], [{"node": "kimbap", "paths": ["/var/mnt/datasets/truenas/clusters/mbk"]}])
        self.assertEqual(backups["storageClass"]["reclaimPolicy"], "Retain")
        self.assertEqual(classes["local-path"]["nodePathMap"][0]["paths"], ["/var/mnt/local-path-provisioner"])

    def test_scripts_and_destinations_resolve_in_the_app_namespace(self):
        jobs = [item for item in self.resources.values() if item["kind"] == "CronJob"
                and item["metadata"]["name"] in ("file-backup", "postgres-backup")]
        self.assertTrue(jobs)
        for job in jobs:
            namespace = job["metadata"]["namespace"]
            with self.subTest(namespace=namespace, job=job["metadata"]["name"]):
                self.assertEqual(job["spec"]["timeZone"], "Australia/Sydney")
                pod = job["spec"]["jobTemplate"]["spec"]["template"]["spec"]
                self.assertFalse(pod["automountServiceAccountToken"])
                volumes = {volume["name"]: volume for volume in pod["volumes"]}
                script = volumes["scripts"]["configMap"]["name"]
                self.assertIn(("ConfigMap", namespace, script), self.resources)
                claim = volumes["backups"]["persistentVolumeClaim"]["claimName"]
                destination = self.resources[("PersistentVolumeClaim", namespace, claim)]
                self.assertEqual(destination["spec"]["storageClassName"], "local-backups")
                for container in pod["containers"]:
                    for mount in container["volumeMounts"]:
                        volume = volumes[mount["name"]]
                        if mount["mountPath"].startswith("/source"):
                            self.assertTrue(mount["readOnly"])
                            self.assertTrue(volume["persistentVolumeClaim"]["readOnly"])
                            self.assertNotEqual(volume["persistentVolumeClaim"]["claimName"], claim)
                            source = self.resources.get((
                                "PersistentVolumeClaim", namespace,
                                volume["persistentVolumeClaim"]["claimName"],
                            ))
                            annotations = source["metadata"].get("annotations", {}) if source else {}
                            uid = annotations.get("local-path-provisioner/userPattern")
                            if uid is not None:
                                self.assertEqual(pod["securityContext"]["runAsUser"], int(uid))

    def test_each_postgres_backup_uses_its_cluster_image_owner_and_ingress(self):
        clusters = [item for item in self.resources.values() if item["kind"] == "Cluster"
                    and item["apiVersion"] == "postgresql.cnpg.io/v1"]
        self.assertTrue(clusters)
        for cluster in clusters:
            namespace = cluster["metadata"]["namespace"]
            with self.subTest(namespace=namespace):
                job = self.resources[("CronJob", namespace, "postgres-backup")]
                pod = job["spec"]["jobTemplate"]["spec"]["template"]["spec"]
                container = pod["containers"][0]
                self.assertEqual(container["image"], cluster["spec"]["imageName"])
                environment = {entry["name"]: entry for entry in container["env"]}
                self.assertEqual(environment["PGHOST"]["value"], cluster["metadata"]["name"] + "-rw")
                initdb = cluster["spec"]["bootstrap"]["initdb"]
                self.assertEqual(environment["PGDATABASE"]["value"], initdb["database"])
                for name in ("PGPASSWORD", "PGUSER"):
                    self.assertEqual(environment[name]["valueFrom"]["secretKeyRef"]["name"], initdb["secret"]["name"])
                if namespace == "litellm":
                    continue
                policy = self.resources[("NetworkPolicy", namespace, "postgres-backup")]["spec"]
                self.assertEqual(policy["podSelector"]["matchLabels"]["cnpg.io/cluster"], cluster["metadata"]["name"])
                selector = policy["ingress"][0]["from"][0]["podSelector"]["matchLabels"]
                self.assertEqual(selector, job["spec"]["jobTemplate"]["spec"]["template"]["metadata"]["labels"])

    def test_backups_preserve_the_existing_database_isolation_boundary(self):
        # LiteLLM's migration hooks must retain their previously unrestricted access.
        self.assertNotIn(("NetworkPolicy", "litellm", "postgres-backup"), self.resources)
        for namespace in ("bookorbit", "immich", "linkwarden", "miniflux", "pocket-id", "romm"):
            with self.subTest(namespace=namespace):
                self.assertIn(("NetworkPolicy", namespace, namespace + "-database"), self.resources)
                self.assertIn(("NetworkPolicy", namespace, "postgres-backup"), self.resources)


if __name__ == "__main__":
    unittest.main()
