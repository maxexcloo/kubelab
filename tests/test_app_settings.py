"""Shared app policy and derived settings must survive native composition."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read_yaml(path):
    # Resolve YAML merges before rewriting whole documents as JSON.
    return json.loads(subprocess.check_output([
        "yq", "--yaml-fix-merge-anchor-to-spec", "-o=json", ".", str(path)
    ]))


class AppSettingsTests(unittest.TestCase):
    def test_owned_probe_timing_policy(self):
        for cluster in ("syd",):
            output = subprocess.check_output(
                ["kubectl", "kustomize", str(ROOT / "apps/overlays" / cluster)], text=True
            )
            documents = subprocess.check_output(
                ["yq", "-I=0", "-N", "-o=json", "."], input=output, text=True
            )
            checked = 0
            for resource in map(json.loads, documents.splitlines()):
                if resource["kind"] == "HelmRelease":
                    if resource["metadata"]["name"] == "homepage":
                        continue
                    if resource["spec"].get("chart", {}).get("spec", {}).get("chart") != "app-template":
                        continue
                    probes = [
                        (name, probe.get("spec", {}))
                        for controller in resource["spec"]["values"].get("controllers", {}).values()
                        for container in controller.get("containers", {}).values()
                        for name, probe in container.get("probes", {}).items()
                        if probe.get("enabled")
                    ]
                elif resource["kind"] == "DaemonSet" and resource["metadata"]["name"] == "beszel-agent":
                    probes = [
                        (name.removesuffix("Probe"), probe)
                        for container in resource["spec"]["template"]["spec"]["containers"]
                        for name, probe in container.items()
                        if name in ("livenessProbe", "readinessProbe", "startupProbe")
                    ]
                else:
                    continue
                for name, probe in probes:
                    with self.subTest(cluster=cluster, app=resource["metadata"]["name"], probe=name):
                        self.assertEqual(probe.get("periodSeconds", 10), 10)
                        self.assertEqual(probe.get("timeoutSeconds", 1), 5)
                        self.assertEqual(probe.get("failureThreshold", 3), 30 if name == "startup" else 3)
                    checked += 1
            self.assertGreater(checked, 0)

    def test_hostname_changes_reach_all_consumers(self):
        app_directory = ROOT / "apps/base"
        configuration_files = sorted(
            {*app_directory.glob("*/helm-release.yaml"), *app_directory.glob("*/*settings.yaml")}
        )
        for settings in configuration_files:
            resource = read_yaml(settings)
            if not isinstance(resource, dict) or resource.get("kind") != "HelmRelease":
                continue
            routes = resource["spec"]["values"].get("route", {})
            routes = [routes] if "hostnames" in routes else routes.values()
            for route in routes:
                if "hostnames" not in route:
                    continue
                for index, old in enumerate(list(route["hostnames"])):
                    # Derived route placeholders receive their hostname from another owner.
                    if old.endswith(".invalid"):
                        continue
                    with self.subTest(app=settings.parent.name, hostname=old), tempfile.TemporaryDirectory() as directory:
                        app = Path(directory) / "apps/base" / settings.parent.name
                        app.parent.mkdir(parents=True)
                        shutil.copytree(ROOT / "apps/components", Path(directory) / "apps/components")
                        shutil.copytree(ROOT / "platform/backups", Path(directory) / "platform/backups")
                        if settings.parent.name == "homepage":
                            shutil.copytree(ROOT / "scripts/service-routes", Path(directory) / "scripts/service-routes")
                        shutil.copytree(settings.parent, app)
                        route["hostnames"][index] = "renamed.example.test"
                        (app / settings.name).write_text(json.dumps(resource))
                        output = subprocess.check_output(["kubectl", "kustomize", str(app)], text=True)
                        self.assertIn("renamed.example.test", output)
                        self.assertNotIn(old, output)
                        self.assertNotIn("app.invalid", output)
                        self.assertNotIn("alias.invalid", output)
                    route["hostnames"][index] = old

    def test_persistent_volumes_use_direct_kimbap_datasets(self):
        output = subprocess.check_output(
            ["kubectl", "kustomize", str(ROOT / "apps/overlays/syd")], text=True
        )
        documents = subprocess.check_output(
            ["yq", "-I=0", "-N", "-o=json", "."], input=output, text=True
        )
        volumes = [item for item in map(json.loads, documents.splitlines())
                   if item["kind"] == "PersistentVolume"]
        self.assertTrue(volumes)
        for volume in volumes:
            self.assertNotIn("nfs", volume["spec"])
            self.assertTrue(volume["spec"]["hostPath"]["path"].startswith("/var/mnt/datasets/"))
            terms = volume["spec"]["nodeAffinity"]["required"]["nodeSelectorTerms"]
            self.assertEqual(terms[0]["matchExpressions"][0]["values"], ["kimbap"])

    def test_shared_beszel_hostname_changes_reach_syd(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("apps", "clusters", "platform", "scripts"):
                shutil.copytree(ROOT / name, root / name)
            settings = root / "platform/settings/settings.yaml"
            resource = read_yaml(settings)
            resource["data"]["beszel_host"] = "renamed.example.test"
            settings.write_text(json.dumps(resource))
            for cluster in ("syd",):
                with self.subTest(cluster=cluster):
                    output = subprocess.check_output(
                        ["kubectl", "kustomize", str(root / "apps/overlays" / cluster)],
                        text=True,
                    )
                    documents = subprocess.check_output(
                        ["yq", "-I=0", "-N", "-o=json", "."],
                        input=output,
                        text=True,
                    )
                    resources = {
                        (item["kind"], item["metadata"]["name"]): item
                        for item in map(json.loads, documents.splitlines())
                    }
                    agent = resources[("DaemonSet", "beszel-agent")]
                    container = next(
                        item
                        for item in agent["spec"]["template"]["spec"]["containers"]
                        if item["name"] == "beszel-agent"
                    )
                    hub_url = next(
                        item["value"]
                        for item in container["env"]
                        if item["name"] == "HUB_URL"
                    )
                    self.assertEqual(
                        hub_url, "http://beszel.beszel.svc.cluster.local:8090"
                    )
                    values = resources[("HelmRelease", "beszel")]["spec"]["values"]
                    route = values["route"]["private"]
                    self.assertEqual(route["hostnames"], ["renamed.example.test"])
                    env = values["controllers"]["main"]["containers"]["main"]["env"]
                    self.assertEqual(env["APP_URL"], "https://renamed.example.test")
                    for name in ("gethomepage.dev/href", "gethomepage.dev/widget.url"):
                        self.assertEqual(
                            route["annotations"][name], "https://renamed.example.test"
                        )
                    self.assertEqual(
                        resources[("PrivateDNSRecord", "beszel")]["spec"]["hostname"],
                        "renamed.example.test",
                    )
                    client = resources[("PocketIDClient", "beszel")]["spec"]["client"]
                    self.assertEqual(client["launchURL"], "https://renamed.example.test")
                    self.assertEqual(
                        client["callbackURLs"],
                        ["https://renamed.example.test/api/oauth2-redirect"],
                    )

if __name__ == "__main__":
    unittest.main()
