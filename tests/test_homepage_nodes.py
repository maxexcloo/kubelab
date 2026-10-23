"""Check Homepage dashboard nodes without network access."""

import json
import shutil
import unittest

from homepage_support import HOMELAB, HomepageDashboardFixture, beszel_route, route
from support import read_yaml


class HomepageNodesTests(HomepageDashboardFixture, unittest.TestCase):
    def test_native_machine_widgets_use_homelab_identities(self):

        homelab = self.directory / "homelab"
        shutil.copytree(HOMELAB, homelab)
        path = homelab / "data/machines.yaml"
        inventory = read_yaml(path)
        del inventory["machines"]["mbk"]["kimbap"]["services"]["syncthing"]
        inventory["machines"]["mbk"]["kimbap"]["beszel"] = True
        inventory["machines"]["mbk"]["personal"] = {
            "platform": "macos",
            "services": {"management": {"port": 443, "scheme": "https"}},
        }
        inventory["machines"]["mbk"]["sensor"] = {"platform": "slzb"}
        inventory["machines"]["mbk"]["taco"] = {
            "beszel": True,
            "cluster": "mbk",
            "platform": "talos",
            "type": "vm",
        }
        path.write_text(json.dumps(inventory))
        providers_path = homelab / "data/providers.yaml"
        providers = read_yaml(providers_path)
        providers["providers"].update(
            {
                "cloudflare": {
                    "description": "Cloudflare Tunnel",
                    "icon": "cloudflare",
                    "name": "Cloudflare Tunnel",
                    "widget": {
                        "type": "cloudflared",
                        "key": "{{HOMEPAGE_VAR_CLOUDFLARE_API_TOKEN}}",
                    },
                },
                "tailscale": {
                    "description": "VPN",
                    "icon": "tailscale",
                    "name": "Tailscale",
                    "widget": {
                        "type": "tailscale",
                        "key": "{{HOMEPAGE_VAR_TAILSCALE_API_TOKEN}}",
                    },
                },
            }
        )
        for name in ("Cloudflare", "Tailscale"):
            providers["providers"][name.lower()].update(
                {
                    "name": name,
                    "description": name,
                    "icon": name.lower(),
                    "url": f"https://{name.lower()}.example.net",
                }
            )
        providers_path.write_text(json.dumps(providers))
        identities = self.directory / "infrastructure.json"
        identities.write_text(
            json.dumps(
                {
                    "cloudflare": {
                        "account_id": "account",
                        "tunnels": {
                            "kimbap": "storage-tunnel",
                            "mbk": "cluster-tunnel",
                        },
                    },
                    "tailscale": {
                        "kimbap": "storage-device",
                        "mbk": "cluster-device",
                        "taco": "node-device",
                        "personal": "personal-device",
                    },
                }
            )
        )
        beszel = beszel_route()
        self.write_routes("mbk", [beszel])
        result = self.render(
            HOMELAB_DIRECTORY=str(homelab), HOMELAB_INFRASTRUCTURE_FILE=str(identities)
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        services = self.services()
        self.assertNotIn("mbk-kimbap", services)
        self.assertNotIn("mbk-sensor", services)
        groups = {
            name: {key: value for card in cards for key, value in card.items()}
            for name, cards in self.groups().items()
        }
        self.assertNotIn("mbk-personal", groups)
        self.assertIn("Netboot", groups["Infrastructure"])
        self.assertIn("ESPHome", groups["Smart Home"])
        self.assertIn("Home Assistant", groups["Smart Home"])
        self.assertNotIn("widget", groups["Smart Home"]["Home Assistant"])
        self.assertEqual(
            groups["Overview"]["Home Assistant"]["widget"],
            groups["mbk-hass"]["Home Assistant"]["widget"],
        )
        # Taller cards end the Overview grid: TrueNAS adds pool rows to its widget.
        self.assertEqual(list(groups["Overview"])[-1], "TrueNAS")
        self.assertEqual(
            groups["Smart Home"]["Home Assistant"]["description"],
            "Smart Home & Automations • mbk-hass",
        )
        storage = groups["mbk-storage"]
        # Larger cards lead: TrueNAS adds pool rows to its widget.
        self.assertEqual(
            list(storage), ["TrueNAS", "Beszel", "Cloudflare", "Tailscale"]
        )
        self.assertEqual(storage["TrueNAS"]["widget"]["type"], "truenas")
        self.assertTrue(storage["TrueNAS"]["widget"]["enablePools"])
        self.assertNotIn("widgets", storage["TrueNAS"])
        node = groups["mbk-taco"]
        self.assertEqual(list(node), ["Beszel", "Tailscale"])
        self.assertEqual(node["Beszel"]["widget"]["systemId"], "mbk-taco")
        self.assertEqual(
            node["Beszel"]["href"], "https://beszel.example.net/system/mbk-taco"
        )
        self.assertEqual(node["Tailscale"]["widget"]["deviceid"], "node-device")
        self.assertEqual(
            groups["mbk"]["Cloudflare"]["widget"]["tunnelid"], "cluster-tunnel"
        )
        self.assertEqual(
            groups["mbk"]["Tailscale"]["widget"]["deviceid"], "cluster-device"
        )
        self.assertEqual(
            node["Tailscale"]["widget"]["key"], "{{HOMEPAGE_VAR_TAILSCALE_API_TOKEN}}"
        )
        self.assertEqual(
            node["Tailscale"]["href"],
            "https://login.tailscale.com/admin/machines/node-device",
        )
        self.assertEqual(
            node["Beszel"]["widget"]["password"], "{{HOMEPAGE_VAR_BESZEL_PASSWORD}}"
        )
        self.assertEqual(
            node["Beszel"]["widget"]["fields"], ["status", "cpu", "memory", "network"]
        )
        self.assertEqual(node["Beszel"]["weight"], -1)
        self.assertEqual(node["Beszel"]["icon"], "sh-beszel")
        layout = read_yaml(self.output / "settings.yaml")["layout"]
        for group in ["mbk-storage", "mbk-taco"]:
            self.assertEqual(layout["Servers"]["tab"], "Servers")
            self.assertIn(group, layout["Servers"])
        for group in ["Infrastructure", "Operations", "Smart Home"]:
            self.assertEqual(layout["Home"]["tab"], "Home")
            self.assertIn(group, layout["Home"])
        before = (self.output / "services.yaml").read_bytes()
        identities.write_text("{broken json")
        self.assertNotEqual(
            self.render(
                HOMELAB_DIRECTORY=str(homelab),
                HOMELAB_INFRASTRUCTURE_FILE=str(identities),
            ).returncode,
            0,
        )
        self.assertEqual((self.output / "services.yaml").read_bytes(), before)

    def test_cluster_tools_support_multiple_nodes_without_inventing_placement(self):

        homelab = self.directory / "homelab"
        shutil.copytree(HOMELAB, homelab)
        path = homelab / "data/machines.yaml"
        inventory = read_yaml(path)
        del inventory["machines"]["mbk"]["taco"]
        inventory["machines"]["mbk"]["node"] = {
            "cluster": "mbk",
            "hostname": "renamed",
            "type": "vm",
        }
        inventory["machines"]["syd"] = {"node": {"cluster": "syd", "type": "vm"}}
        path.write_text(json.dumps(inventory))
        for cluster in ("mbk", "syd"):
            tool = route("Headlamp", group="Operations", instance="inventory")
            tool["metadata"]["namespace"] = "headlamp"
            self.write_routes(cluster, [tool])
        result = self.render(HOMELAB_DIRECTORY=str(homelab))
        self.assertEqual(result.returncode, 0, result.stderr)
        groups = self.groups()
        local = groups["mbk/node"][0]["Headlamp"]
        remote = groups["syd"][0]["Headlamp"]
        self.assertEqual(local["namespace"], "headlamp")
        self.assertEqual(local["app"], "headlamp")
        self.assertNotIn("namespace", remote)
        layout = read_yaml(self.output / "settings.yaml")["layout"]
        self.assertEqual(layout["Clusters"]["tab"], "Clusters")
        self.assertIn("mbk/node", layout["Clusters"])
        self.assertIn("syd", layout["Clusters"])
        self.assertEqual(layout["Home"]["tab"], "Home")
        self.assertIn("Servers", layout)
        before = (self.output / "services.yaml").read_bytes()
        inventory["machines"]["mbk"]["extra"] = {"cluster": "mbk", "type": "vm"}
        path.write_text(json.dumps(inventory))
        self.assertEqual(self.render(HOMELAB_DIRECTORY=str(homelab)).returncode, 0)
        self.assertEqual((self.output / "services.yaml").read_bytes(), before)

    def test_native_node_widget_and_local_pod_stats_follow_cluster_selection(self):
        self.write_routes(
            "mbk",
            [
                route("Local", **{"pod-selector": "app=local"}),
                route("Compact", showStats="false"),
            ],
        )
        for cluster in ("mbk", "syd"):
            with self.subTest(cluster=cluster):
                result = self.render(HOMEPAGE_CLUSTER=cluster)
                self.assertEqual(result.returncode, 0, result.stderr)
                widgets = read_yaml(self.output / "widgets.yaml")
                self.assertEqual(
                    widgets[0]["unifi_console"],
                    {
                        "key": "{{HOMEPAGE_VAR_UNIFI_API_KEY}}",
                        "url": "https://gateway.mbk.example.net",
                    },
                )
                kubernetes = next(
                    widget["kubernetes"] for widget in widgets if "kubernetes" in widget
                )
                self.assertEqual(kubernetes["cluster"]["label"], cluster)
                self.assertIn(
                    f'--homepage-cluster: "{cluster}"',
                    (self.output / "custom.css").read_text(),
                )
                for scope in ("cluster", "nodes"):
                    for option in ("cpu", "memory", "show", "showLabel"):
                        self.assertIs(kubernetes[scope][option], True)
                # Nodes are discovered by Homepage, never copied from host inventory.
                self.assertEqual(set(kubernetes), {"cluster", "nodes"})
                services = self.services()
                local, remote = (
                    ("Local", "Remote") if cluster == "mbk" else ("Remote", "Local")
                )
                self.assertNotIn("showStats", services[local])
                self.assertEqual(services[local]["namespace"], local.lower())
                for option in ("app", "namespace", "podSelector", "showStats"):
                    self.assertNotIn(option, services[remote])
                if cluster == "mbk":
                    self.assertEqual(services[local]["podSelector"], "app=local")
                    self.assertIs(services["Compact"]["showStats"], False)
                layout = read_yaml(self.output / "settings.yaml")["layout"]
                self.assertEqual(layout["Clusters"]["tab"], "Clusters")

    def test_live_placement_follows_rescheduling_selectors_and_unscheduled_apps(self):
        self.write_routes(
            "mbk",
            [
                route("Reader", **{"pod-selector": "app in (reader,feeds)"}),
                route("Waiting"),
            ],
        )
        self.placements.write_text(
            json.dumps({"reader": ["hsp", "kimbap", "hsp"], "waiting": []})
        )
        result = self.render()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            set(self.groups("Clusters")),
            {"mbk/hsp", "mbk/kimbap", "mbk/unscheduled", "syd"},
        )
        self.assertIn("Reader", self.groups("Clusters")["mbk/hsp"][0])
        self.assertIn("Reader", self.groups("Clusters")["mbk/kimbap"][0])
        queries = [json.loads(line) for line in self.queries.read_text().splitlines()]
        self.assertTrue(any(query[-1] == "app in (reader,feeds)" for query in queries))
        self.assertTrue(all(query[1] != "remote" for query in queries))
        self.placements.write_text(json.dumps({"reader": ["renamed"], "waiting": []}))
        self.assertEqual(self.render().returncode, 0)
        self.assertIn("mbk/renamed", self.groups("Clusters"))
        self.assertNotIn("mbk/hsp", self.groups("Clusters"))
        before = (self.output / "services.yaml").read_bytes()
        self.placements.write_text(json.dumps({"reader": "fail"}))
        self.assertNotEqual(self.render().returncode, 0)
        self.assertEqual((self.output / "services.yaml").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
