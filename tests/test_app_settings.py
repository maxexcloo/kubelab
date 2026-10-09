"""Changing an app hostname must update every native consumer without extra edits."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read_yaml(path):
    return json.loads(subprocess.check_output(["yq", "-o=json", ".", str(path)]))


class AppSettingsTests(unittest.TestCase):
    def test_hostname_changes_reach_all_consumers(self):
        settings_files = sorted((ROOT / "apps/base").glob("*/*settings.yaml"))
        for settings in settings_files:
            resource = read_yaml(settings)
            if not isinstance(resource, dict) or resource.get("kind") != "HelmRelease":
                continue
            routes = resource["spec"]["values"].get("route", {})
            routes = [routes] if "hostnames" in routes else routes.values()
            for route in routes:
                if "hostnames" not in route:
                    continue
                for index, old in enumerate(list(route["hostnames"])):
                    with self.subTest(app=settings.parent.name, hostname=old), tempfile.TemporaryDirectory() as directory:
                        app = Path(directory) / settings.parent.name
                        shutil.copytree(settings.parent, app)
                        route["hostnames"][index] = "renamed.example.test"
                        (app / settings.name).write_text(json.dumps(resource))
                        output = subprocess.check_output(["kustomize", "build", str(app)], text=True)
                        self.assertIn("renamed.example.test", output)
                        self.assertNotIn(old, output)
                        self.assertNotIn("app.invalid", output)
                        self.assertNotIn("alias.invalid", output)
                    route["hostnames"][index] = old

    def test_shared_beszel_hostname_changes_reach_both_clusters(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("apps", "clusters", "platform"):
                shutil.copytree(ROOT / name, root / name)
            settings = root / "platform/settings/settings.yaml"
            resource = read_yaml(settings)
            resource["data"]["beszel_host"] = "renamed.example.test"
            settings.write_text(json.dumps(resource))
            for cluster in ("mbk", "syd"):
                with self.subTest(cluster=cluster):
                    output = subprocess.check_output(
                        ["kustomize", "build", str(root / "apps/overlays" / cluster)],
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
                    if cluster == "syd":
                        self.assertEqual(hub_url, "https://renamed.example.test")
                        continue
                    self.assertEqual(
                        hub_url, "http://beszel.beszel.svc.cluster.local:8090"
                    )
                    values = resources[("HelmRelease", "beszel")]["spec"]["values"]
                    route = values["route"]["private"]
                    self.assertEqual(route["hostnames"], ["renamed.example.test"])
                    env = values["controllers"]["beszel"]["containers"]["beszel"]["env"]
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
