"""Shared settings must reach each Flux boundary without deploying helper resources."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read_yaml(path):
    return json.loads(subprocess.check_output(["yq", "-o=json", ".", str(path)]))


class ClusterSettingsTests(unittest.TestCase):
    def test_shared_settings_reach_apps_platform_and_integrations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("apps", "clusters", "platform", "scripts"):
                shutil.copytree(ROOT / name, root / name)
            shared = root / "platform/settings/settings.yaml"
            settings = read_yaml(shared)
            settings["data"]["identity_host"] = "id.changed.example"
            settings["data"]["control_d_profile"] = "test-profile"
            shared.write_text(json.dumps(settings))
            cluster = root / "clusters/mbk/settings/settings.yaml"
            settings = read_yaml(cluster)
            settings["data"].update({
                "bento_address": "192.0.2.15",
                "grafana_host": "grafana.changed.example",
                "nfs_server": "192.0.2.12",
                "private_dns_host": "private.changed.example",
                "unifi_host": "gateway.changed.example",
            })
            cluster.write_text(json.dumps(settings))
            output = root / "rendered"
            subprocess.run(["scripts/render_manifests.sh", str(output)], cwd=root, check=True)
            resources = []
            for path in output.rglob("*.yaml"):
                rendered = path.read_text()
                for unresolved in ("app.invalid", "identity.invalid", "storage.invalid", "id.excloo.com", "grafana.excloo.com", "10.4.0.3"):
                    self.assertNotIn(unresolved, rendered, str(path))
                resources.extend(json.loads(subprocess.check_output(["yq", "ea", "-o=json", "[.]", str(path)])))
            resources = [r for r in resources if r]
            self.assertFalse(any(r["metadata"]["name"].startswith(("cluster-settings-", "shared-settings")) for r in resources))
            litellm = next(r for r in resources if r["kind"] == "HelmRelease" and r["metadata"]["name"] == "litellm")
            values = litellm["spec"]["values"]
            bento = next(d for d in values["proxy_config"]["model_list"] if d["model_name"].startswith("bento/"))
            self.assertEqual(bento["litellm_params"]["api_base"], "http://192.0.2.15:8000/v1")
            self.assertEqual(values["envVars"]["UNIFI_NETWORK_HOST"], "gateway.changed.example")
            heiss = next(r for r in resources if r["kind"] == "EndpointSlice" and r["metadata"]["name"] == "heiss-mcp")
            self.assertEqual(heiss["endpoints"][0]["addresses"], ["192.0.2.15"])
            self.assertEqual(heiss["ports"][0]["port"], 1338)
            volumes = [r for r in resources if r["kind"] == "PersistentVolume" and "nfs" in r["spec"]]
            self.assertTrue(volumes)
            self.assertEqual({r["spec"]["nfs"]["server"] for r in volumes}, {"192.0.2.12"})
            grafana = [r for r in resources if r["kind"] == "PocketIDClient" and r["metadata"]["name"] == "grafana"]
            self.assertEqual(grafana[0]["spec"]["client"]["launchURL"], "https://grafana.changed.example")
            defaults = [r["spec"]["versions"][0]["schema"]["openAPIV3Schema"]["properties"]["spec"]["properties"]["controlDProfileID"]["default"]
                        for r in resources if r["kind"] == "CompositeResourceDefinition" and r["metadata"]["name"] == "privatednsrecords.automation.excloo.dev"]
            self.assertEqual(set(defaults), {"test-profile"})


if __name__ == "__main__":
    unittest.main()
