"""Shared settings must reach each Flux boundary without deploying helper resources."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from support import copy_repository, read_resources, read_yaml


class ClusterSettingsTests(unittest.TestCase):
    def test_shared_settings_reach_apps_platform_and_integrations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            copy_repository(root)
            shared = root / "platform/settings/settings.yaml"
            settings = read_yaml(shared)
            settings["data"]["headlamp_client_id"] = "headlamp-test"
            settings["data"]["headlamp_syd_host"] = "headlamp.syd.changed.example"
            settings["data"]["identity_host"] = "id.changed.example"
            settings["data"]["control_d_profile"] = "test-profile"
            shared.write_text(json.dumps(settings))
            cluster = root / "clusters/syd/settings/settings.yaml"
            settings = read_yaml(cluster)
            settings["data"].update({
                "bento_address": "192.0.2.15",
                "grafana_host": "grafana.changed.example",
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
                resources.extend(read_resources(path))
            self.assertFalse(any(r["metadata"]["name"].startswith(("cluster-settings-", "shared-settings")) for r in resources))
            # Defaults only affect creation; explicit targets migrate existing DNS records too.
            dns_records = [r for r in resources if r["kind"] == "PrivateDNSRecord"]
            self.assertTrue(dns_records)
            self.assertEqual({r["spec"]["target"] for r in dns_records}, {"private.changed.example"})
            litellm = next(r for r in resources if r["kind"] == "HelmRelease" and r["metadata"]["name"] == "litellm")
            values = litellm["spec"]["values"]
            bento = next(d for d in values["proxy_config"]["model_list"] if d["model_name"].startswith("bento/"))
            self.assertEqual(bento["litellm_params"]["api_base"], "http://192.0.2.15:8000/v1")
            self.assertEqual(values["envVars"]["UNIFI_NETWORK_HOST"], "gateway.changed.example")
            heiss = next(r for r in resources if r["kind"] == "EndpointSlice" and r["metadata"]["name"] == "heiss-mcp")
            self.assertEqual(heiss["endpoints"][0]["addresses"], ["192.0.2.15"])
            self.assertEqual(heiss["ports"][0]["port"], 1338)
            volumes = [r for r in resources if r["kind"] == "PersistentVolume"]
            self.assertTrue(volumes)
            self.assertFalse(any("nfs" in r["spec"] for r in volumes))
            grafana = [r for r in resources if r["kind"] == "PocketIDClient" and r["metadata"]["name"] == "grafana"]
            self.assertEqual(grafana[0]["spec"]["client"]["launchURL"], "https://grafana.changed.example")
            self.assertEqual(grafana[0]["spec"]["client"]["callbackURLs"], [
                "https://grafana.changed.example/login/generic_oauth",
            ])
            grafana_releases = [r for r in resources if r["kind"] == "HelmRelease"
                                and r["metadata"]["name"] == "victoria-metrics-k8s-stack"]
            self.assertEqual(len(grafana_releases), 1)
            self.assertEqual({r["spec"]["values"]["grafana"]["grafana.ini"]["server"]["root_url"]
                              for r in grafana_releases}, {
                "https://grafana.changed.example",
            })
            for release in grafana_releases:
                oauth = release["spec"]["values"]["grafana"]["grafana.ini"]["auth.generic_oauth"]
                self.assertTrue(oauth["enabled"])
                self.assertEqual(oauth["auth_url"], "https://id.changed.example/authorize")
            headlamp_client = next(r for r in resources if r["kind"] == "PocketIDClient"
                                   and r["metadata"]["name"] == "headlamp")["spec"]["client"]
            self.assertEqual(headlamp_client["callbackURLs"], [
                "https://headlamp.syd.changed.example/oidc-callback",
            ])
            self.assertEqual(headlamp_client["launchURL"], "https://headlamp.syd.changed.example")
            self.assertEqual(headlamp_client["id"], "headlamp-test")
            self.assertTrue(headlamp_client["isPublic"])
            self.assertTrue(headlamp_client["pkceEnabled"])
            headlamp_releases = [r for r in resources if r["kind"] == "HelmRelease"
                                 and r["metadata"]["name"] == "headlamp"]
            self.assertEqual(len(headlamp_releases), 1)
            self.assertEqual({r["spec"]["values"]["config"]["oidc"]["callbackURL"]
                              for r in headlamp_releases}, set(headlamp_client["callbackURLs"]))
            for release in headlamp_releases:
                oidc = release["spec"]["values"]["config"]["oidc"]
                self.assertEqual(oidc["clientID"], headlamp_client["id"])
                self.assertEqual(oidc["issuerURL"], "https://id.changed.example")
                self.assertEqual(oidc["scopes"], "profile,email,groups")
                self.assertTrue(oidc["usePKCE"])
                self.assertFalse(oidc["secret"]["create"])
            defaults = [r["spec"]["versions"][0]["schema"]["openAPIV3Schema"]["properties"]["spec"]["properties"]["controlDProfileID"]["default"]
                        for r in resources if r["kind"] == "CompositeResourceDefinition" and r["metadata"]["name"] == "privatednsrecords.automation.excloo.dev"]
            self.assertEqual(set(defaults), {"test-profile"})


if __name__ == "__main__":
    unittest.main()
