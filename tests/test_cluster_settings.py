"""Shared settings must reach each Flux boundary without deploying helper resources."""

import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from support import CLUSTERS, ROOT, copy_repository, read_resources, read_yaml

# Base manifests use these until settings or route replacements resolve them.
# Crossplane composition templates keep pending.invalid and placeholder.invalid
# for their functions to patch at runtime.
PLACEHOLDER = re.compile(r"(?<![\w-])[\w-]+(?:\.[\w-]+)*\.invalid\b|\.cluster\.excloo\.dev\b|profile-placeholder")
RUNTIME_PLACEHOLDERS = {"pending.invalid", "placeholder.invalid"}


def rendered_resources(test, root):
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory)
        subprocess.run(["scripts/render_manifests.sh", str(output)], cwd=root, check=True)
        resources = []
        for path in sorted(output.rglob("*.yaml")):
            for resource in read_resources(path):
                text = json.dumps(resource)
                unresolved = [item for item in PLACEHOLDER.findall(text) if item not in RUNTIME_PLACEHOLDERS]
                test.assertEqual(unresolved, [], f"{path.relative_to(output)}: {resource['kind']}/{resource['metadata']['name']}")
                resources.append(resource)
        return resources


class ClusterSettingsTests(unittest.TestCase):
    def test_every_flux_path_resolves_placeholders(self):
        self.assertTrue(rendered_resources(self, ROOT))

    def test_shared_settings_reach_apps_platform_and_integrations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            copy_repository(root)
            shared = root / "platform/settings/settings.yaml"
            settings = read_yaml(shared)
            settings["data"]["headlamp_client_id"] = "headlamp-test"
            settings["data"]["identity_host"] = "id.changed.example"
            settings["data"]["control_d_profile"] = "test-profile"
            shared.write_text(json.dumps(settings))
            for cluster in CLUSTERS:
                path = root / "clusters" / cluster / "settings/settings.yaml"
                settings = read_yaml(path)
                settings["data"].update({
                    "bento_address": "192.0.2.15",
                    "bento_llm_authority": "bento.changed.example:8123",
                    "cluster_name": "renamed",
                    "grafana_host": "grafana.changed.example",
                    "headlamp_host": "headlamp.cluster.changed.example",
                    "home_assistant_host": "hass.changed.example",
                    "private_dns_host": "private.cluster.changed.example",
                    "unifi_host": "gateway.changed.example",
                })
                path.write_text(json.dumps(settings))
            resources = rendered_resources(self, root)
            rendered = json.dumps(resources)
            for unresolved in ("id.excloo.com", "grafana.excloo.com"):
                self.assertNotIn(unresolved, rendered)
            self.assertFalse(any(r["metadata"]["name"].startswith(("cluster-settings", "shared-settings")) for r in resources))
            # Defaults only affect creation; explicit targets migrate existing DNS records too.
            dns_records = [r for r in resources if r["kind"] == "PrivateDNSRecord"]
            self.assertTrue(dns_records)
            self.assertEqual({r["spec"]["target"] for r in dns_records}, {"private.renamed.changed.example"})
            litellm = next(r for r in resources if r["kind"] == "HelmRelease" and r["metadata"]["name"] == "litellm")
            values = litellm["spec"]["values"]
            librechat = next(r for r in resources if r["kind"] == "HelmRelease" and r["metadata"]["name"] == "librechat")
            self.assertEqual(librechat["spec"]["values"]["librechat"]["configEnv"]["BENTO_API_URL"],
                             "http://bento.changed.example:8123/v1")
            ai = next(m for m in values["proxy_config"]["model_list"] if m["model_name"] == "ai/*")
            self.assertEqual(ai["litellm_params"]["api_base"], "http://bento.changed.example:8123/v1")
            def main_env(name):
                release = next(r for r in resources if r["kind"] == "HelmRelease" and r["metadata"]["name"] == name)
                return release["spec"]["values"]["controllers"]["main"]["containers"]["main"]["env"]
            self.assertEqual(main_env("home-assistant-mcp")["HOMEASSISTANT_URL"], "https://hass.changed.example")
            self.assertEqual(main_env("unifi-network-mcp")["UNIFI_NETWORK_HOST"], "gateway.changed.example")
            env = main_env("studio")
            self.assertEqual(env["BENTO_ADDRESS"], "192.0.2.15")
            self.assertEqual(env["STUDIO_OIDC_ISSUER"], "https://id.changed.example")
            self.assertEqual(env["ROUTE_ALIAS_HOST"], "studio.renamed.excloo.dev")
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
                "https://headlamp.renamed.changed.example/oidc-callback",
            ])
            self.assertEqual(headlamp_client["launchURL"], "https://headlamp.renamed.changed.example")
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
            # Cluster zone names follow the cluster name.
            certificate = next(r for r in resources if r["kind"] == "Certificate" and r["metadata"]["name"] == "wildcard")
            self.assertIn("*.renamed.excloo.dev", certificate["spec"]["dnsNames"])
            targets = {r["metadata"]["name"]: r["metadata"]["annotations"]["external-dns.alpha.kubernetes.io/target"]
                       for r in resources if r["kind"] == "Gateway" and r["metadata"]["name"].startswith("public-")}
            self.assertEqual(targets, {"public-direct": "public.renamed.excloo.dev", "public-tunnel": "tunnel.renamed.excloo.dev"})
            actual_up = next(r for r in resources if r["kind"] == "HelmRelease" and r["metadata"]["name"] == "actual-up")
            self.assertEqual(actual_up["spec"]["values"]["route"]["private"]["hostnames"], ["actual-up.renamed.excloo.dev"])
            self.assertEqual(actual_up["spec"]["values"]["route"]["private"]["annotations"]["gethomepage.dev/href"],
                             "https://actual-up.renamed.excloo.dev")
            defaults = [r["spec"]["versions"][0]["schema"]["openAPIV3Schema"]["properties"]["spec"]["properties"]["controlDProfileID"]["default"]
                        for r in resources if r["kind"] == "CompositeResourceDefinition" and r["metadata"]["name"] == "privatednsrecords.automation.excloo.dev"]
            self.assertEqual(set(defaults), {"test-profile"})


if __name__ == "__main__":
    unittest.main()
