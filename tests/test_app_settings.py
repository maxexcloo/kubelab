"""Shared app policy and derived settings must survive native composition."""

import unittest

from support import CLUSTERS, repository_resources


class AppSettingsTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
