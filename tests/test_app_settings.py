"""Shared app policy and derived settings must survive native composition."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from support import (
    CLUSTERS,
    ROOT,
    copy_repository,
    read_yaml,
    render_resources,
    repository_resources,
)


class AppSettingsTests(unittest.TestCase):
    def test_heiss_chat_connections_forward_the_signed_in_user(self):
        resources = repository_resources("apps/overlays/syd")
        configuration = next(
            resource["data"]["librechat.yaml"] for resource in resources
            if resource["kind"] == "ConfigMap"
            and resource["metadata"]["namespace"] == "librechat"
            and "librechat.yaml" in resource.get("data", {})
        )
        chat = json.loads(subprocess.check_output(
            ["yq", "-o=json", "."], input=configuration, text=True
        ))["mcpServers"]
        gateway = next(
            resource["spec"]["values"]["proxy_config"]["mcp_servers"]
            for resource in resources if resource["kind"] == "HelmRelease"
            and resource["metadata"]["name"] == "litellm"
        )
        for client, provider in [("heiss", "HEISS"), ("heiss-x", "HEISS_X")]:
            with self.subTest(client=client):
                self.assertEqual(chat[client]["headers"]["X-Bento-User-Id"],
                                 "{{LIBRECHAT_USER_ID}}")
                self.assertIn("X-Bento-User-Id", gateway[provider]["extra_headers"])

    def test_private_aliases_cover_routed_applications(self):
        for cluster in CLUSTERS:
            for path in (f"apps/overlays/{cluster}", f"clusters/{cluster}/platform"):
                for resource in repository_resources(path):
                    if resource["kind"] == "HelmRelease":
                        values = resource["spec"].get("values", {})
                        routes = values.get("route", {})
                        if not routes:
                            continue
                        identity = resource["metadata"]["namespace"]
                        routes = [routes] if "hostnames" in routes else routes.values()
                    elif resource["kind"] == "HTTPRoute":
                        route = resource["spec"]
                        if any(
                            item.get("type") == "RequestRedirect"
                            for rule in route.get("rules", [])
                            for item in rule.get("filters", [])
                        ):
                            continue
                        identity = resource["metadata"]["name"].removesuffix("-private")
                        routes = [route]
                    else:
                        continue
                    alias = f"{identity}.{cluster}.excloo.dev"
                    for route in routes:
                        with self.subTest(cluster=cluster, identity=identity):
                            hosts = route.get("hostnames", [])
                            self.assertEqual(len(hosts), len(set(hosts)))
                            if any(
                                parent["name"] == "private"
                                for parent in route.get("parentRefs", [])
                            ):
                                self.assertIn(alias, hosts)
                            else:
                                self.assertNotIn(alias, hosts)

    def test_database_clients_require_colocation_with_the_primary(self):
        for cluster in CLUSTERS:
            resources = repository_resources(f"apps/overlays/{cluster}")
            databases = [item for item in resources if item["kind"] == "Cluster"]
            self.assertTrue(databases)
            for database in databases:
                namespace = database["metadata"]["namespace"]
                release = next(
                    item
                    for item in resources
                    if item["kind"] == "HelmRelease"
                    and item["metadata"]["namespace"] == namespace
                )
                values = release["spec"]["values"]
                if namespace == "immich":
                    affinity = values["server"]["defaultPodOptions"]["affinity"]
                elif namespace == "litellm":
                    affinity = values["affinity"]
                else:
                    affinity = values["defaultPodOptions"]["affinity"]
                rules = affinity["podAffinity"][
                    "requiredDuringSchedulingIgnoredDuringExecution"
                ]
                with self.subTest(namespace=namespace):
                    self.assertTrue(
                        any(
                            rule["topologyKey"] == "kubernetes.io/hostname"
                            and rule["labelSelector"]["matchLabels"].get(
                                "cnpg.io/instanceRole"
                            )
                            == "primary"
                            and "namespaces" not in rule
                            and "namespaceSelector" not in rule
                            for rule in rules
                        )
                    )

    def test_cluster_applications_follow_network_placement(self):
        external = {
            "aiometadata",
            "aiostreams",
            "cliproxyapi",
            "homepage",
            "openspeedtest",
            "redlib",
        }
        releases = [
            item
            for item in repository_resources("apps/overlays/syd")
            if item["kind"] == "HelmRelease"
        ]
        for release in releases:
            name = release["metadata"]["name"]
            values = release["spec"]["values"]
            chart = release["spec"].get("chart", {}).get("spec", {}).get("chart")
            if chart == "app-template" or name == "immich":
                selector = values["defaultPodOptions"]["nodeSelector"]
            else:
                selector = values["nodeSelector"]
            with self.subTest(application=name):
                self.assertEqual(
                    selector["node.excloo.dev/network"],
                    "external" if name in external else "internal",
                )
        primary = next(
            item for item in releases if item["metadata"]["name"] == "openspeedtest"
        )
        secondary = next(
            item
            for item in releases
            if item["metadata"]["name"] == "openspeedtest-internal"
        )
        self.assertEqual(primary["spec"]["chart"], secondary["spec"]["chart"])
        self.assertNotEqual(
            primary["spec"].get("releaseName"), secondary["spec"].get("releaseName")
        )
        for database in repository_resources("apps/overlays/syd"):
            if database["kind"] == "Cluster":
                self.assertEqual(
                    database["spec"]["affinity"]["nodeSelector"][
                        "node.excloo.dev/network"
                    ],
                    "internal",
                )

    def test_owned_probe_timing_policy(self):
        for cluster in CLUSTERS:
            resources = repository_resources(f"apps/overlays/{cluster}")
            checked = 0
            for resource in resources:
                if resource["kind"] == "HelmRelease":
                    if resource["metadata"]["name"] == "homepage":
                        continue
                    if (
                        resource["spec"].get("chart", {}).get("spec", {}).get("chart")
                        != "app-template"
                    ):
                        continue
                    probes = [
                        (name, probe.get("spec", {}))
                        for controller in resource["spec"]["values"]
                        .get("controllers", {})
                        .values()
                        for container in controller.get("containers", {}).values()
                        for name, probe in container.get("probes", {}).items()
                        if probe.get("enabled")
                    ]
                elif (
                    resource["kind"] == "DaemonSet"
                    and resource["metadata"]["name"] == "beszel-agent"
                ):
                    probes = [
                        (name.removesuffix("Probe"), probe)
                        for container in resource["spec"]["template"]["spec"][
                            "containers"
                        ]
                        for name, probe in container.items()
                        if name in ("livenessProbe", "readinessProbe", "startupProbe")
                    ]
                else:
                    continue
                for name, probe in probes:
                    with self.subTest(
                        cluster=cluster, app=resource["metadata"]["name"], probe=name
                    ):
                        self.assertEqual(probe.get("periodSeconds", 10), 10)
                        self.assertEqual(probe.get("timeoutSeconds", 1), 5)
                        self.assertEqual(
                            probe.get("failureThreshold", 3),
                            30 if name == "startup" else 3,
                        )
                    checked += 1
            self.assertGreater(checked, 0)

    def test_hostname_changes_reach_all_consumers(self):
        app_directory = ROOT / "apps/base"
        configuration_files = sorted(
            {
                *app_directory.glob("*/helm-release.yaml"),
                *app_directory.glob("*/*settings.yaml"),
            }
        )
        for settings in configuration_files:
            resource = read_yaml(settings)
            if not isinstance(resource, dict) or resource.get("kind") != "HelmRelease":
                continue
            routes = resource.get("spec", {}).get("values", {}).get("route", {})
            routes = [routes] if "hostnames" in routes else routes.values()
            for route in routes:
                if "hostnames" not in route:
                    continue
                for index, old in enumerate(list(route["hostnames"])):
                    # Derived route placeholders receive their hostname from another owner.
                    if old.endswith((".invalid", ".cluster.excloo.dev")):
                        continue
                    with (
                        self.subTest(app=settings.parent.name, hostname=old),
                        tempfile.TemporaryDirectory() as directory,
                    ):
                        app = Path(directory) / "apps/base" / settings.parent.name
                        app.parent.mkdir(parents=True)
                        copy_repository(
                            directory,
                            paths=(
                                "apps/components",
                                "apps/transformers",
                                "platform/backups",
                                "platform/databases",
                                "scripts/service-routes",
                            ),
                        )
                        shutil.copytree(settings.parent, app)
                        route["hostnames"][index] = "renamed.example.test"
                        (app / settings.name).write_text(json.dumps(resource))
                        output = subprocess.check_output(
                            ["kubectl", "kustomize", str(app)], text=True
                        )
                        self.assertIn("renamed.example.test", output)
                        self.assertNotIn(old, output)
                        self.assertNotIn("app.invalid", output)
                        self.assertNotIn("alias.invalid", output)
                    route["hostnames"][index] = old

    def test_persistent_volumes_use_direct_kimbap_datasets(self):
        volumes = [
            item
            for item in repository_resources("apps/overlays/syd")
            if item["kind"] == "PersistentVolume"
        ]
        self.assertTrue(volumes)
        for volume in volumes:
            self.assertNotIn("nfs", volume["spec"])
            self.assertTrue(
                volume["spec"]["hostPath"]["path"].startswith("/var/mnt/datasets/")
            )
            terms = volume["spec"]["nodeAffinity"]["required"]["nodeSelectorTerms"]
            self.assertEqual(terms[0]["matchExpressions"][0]["values"], ["kimbap"])

    def test_shared_beszel_hostname_changes_reach_syd(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            copy_repository(root)
            settings = root / "platform/settings/settings.yaml"
            resource = read_yaml(settings)
            resource["data"]["beszel_host"] = "renamed.example.test"
            settings.write_text(json.dumps(resource))
            for cluster in CLUSTERS:
                with self.subTest(cluster=cluster):
                    resources = {
                        (item["kind"], item["metadata"]["name"]): item
                        for item in render_resources(root / "apps/overlays" / cluster)
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
                    self.assertEqual(
                        route["hostnames"],
                        ["renamed.example.test", f"beszel.{cluster}.excloo.dev"],
                    )
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
                    self.assertEqual(
                        client["launchURL"], "https://renamed.example.test"
                    )
                    self.assertEqual(
                        client["callbackURLs"],
                        ["https://renamed.example.test/api/oauth2-redirect"],
                    )


if __name__ == "__main__":
    unittest.main()
