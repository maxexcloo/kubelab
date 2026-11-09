"""Shared app policy and derived settings must survive native composition."""

import ast
import unittest

from support import CLUSTERS, ROOT, read_yaml, repository_resources


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
                        # Per-node instances can retain a deployed namespace identity.
                        if identity == "syncthing":
                            identity = "syncthing-saturn"
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


class BifrostRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        values = read_yaml(ROOT / "apps/base/bifrost/helm-release.yaml")["spec"][
            "values"
        ]
        cls.governance = values["bifrost"]["governance"]

    def test_advertised_cloud_models_each_have_one_route(self):
        router = ast.parse((ROOT / "apps/base/bifrost/router.py").read_text())
        aliases = next(
            ast.literal_eval(statement.value)
            for statement in router.body
            if isinstance(statement, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "ALIASES"
                for target in statement.targets
            )
        )
        studio = read_yaml(ROOT / "apps/base/studio/helm-release.yaml")
        cloud = studio["spec"]["values"]["controllers"]["main"]["containers"]["main"][
            "env"
        ]["STUDIO_ASSISTANT_CLOUD_MODEL"]
        # Studio selects the uncensored counterpart of an auto model.
        self.assertIn(
            cloud.removeprefix("cloud/").replace("auto", "uncensored"), aliases["cloud"]
        )
        for model in aliases["cloud"]:
            with self.subTest(model=model):
                matched = [
                    rule
                    for rule in self.governance["routingRules"]
                    if rule["enabled"]
                    and eval(
                        rule["cel_expression"].replace("&&", "and"),
                        {"__builtins__": {}},
                        {"provider": "cloud", "model": model},
                    )
                ]
                self.assertEqual(len(matched), 1)

    def test_cloud_keys_permit_every_target_and_fallback(self):
        providers = {
            target["provider"]
            for rule in self.governance["routingRules"]
            if rule["enabled"]
            for target in rule["targets"] + rule.get("fallbacks", [])
        }
        for key in self.governance["virtualKeys"]:
            if key.get("allow_all_providers"):
                continue
            allowed = {item["provider"] for item in key.get("provider_configs", [])}
            if "cloud" in allowed:
                with self.subTest(key=key["id"]):
                    self.assertEqual(providers - allowed, set())


if __name__ == "__main__":
    unittest.main()
