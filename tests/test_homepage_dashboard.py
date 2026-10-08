"""Check Homepage's remote annotations and inventory refresh without network access."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "apps/base/homepage"
HOMELAB = ROOT / "tests/fixtures/homepage/homelab"


def read_yaml(path):
    return json.loads(subprocess.check_output(["yq", "-o=json", ".", str(path)]))


def route(name, **annotations):
    return {
        "apiVersion": "gateway.networking.k8s.io/v1",
        "kind": "HTTPRoute",
        "metadata": {
            "name": name.lower(),
            "annotations": {
                "gethomepage.dev/enabled": "true",
                "gethomepage.dev/group": "Applications",
                "gethomepage.dev/href": f"https://{name.lower()}.example.net",
                "gethomepage.dev/name": name,
                **{f"gethomepage.dev/{key}": value for key, value in annotations.items()},
            },
        },
    }


class HomepageDashboardTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.output = self.directory / "output"
        for cluster in ("mbk", "syd"):
            for target in (f"apps/overlays/{cluster}", f"clusters/{cluster}/platform"):
                directory = self.directory / target
                directory.mkdir(parents=True)
                (directory / "kustomization.yaml").write_text("resources: []\n")
        self.write_routes("mbk", [route("Local"), route("Shared")])
        self.write_routes("syd", [route("Remote"), route("Shared"), route("Hidden", enabled="false")])

    def write_routes(self, cluster, resources):
        directory = self.directory / f"apps/overlays/{cluster}"
        (directory / "kustomization.yaml").write_text("resources: [routes.yaml]\n")
        (directory / "routes.yaml").write_text("\n---\n".join(json.dumps(r) for r in resources))

    def render(self, **environment):
        return subprocess.run(
            ["sh", str(APP / "render_dashboard.sh"), str(APP), str(self.output)],
            env=os.environ | {
                "HOMELAB_DIRECTORY": str(HOMELAB),
                "KUBELAB_DIRECTORY": str(self.directory),
                "HOMEPAGE_CLUSTER": "mbk",
            } | environment,
            capture_output=True,
            text=True,
        )

    def services(self):
        return {
            name: service
            for group in read_yaml(self.output / "services.yaml")
            for entries in group.values()
            for entry in entries
            for name, service in entry.items()
        }

    def test_remote_annotations_and_external_machines(self):
        result = self.render()
        self.assertEqual(result.returncode, 0, result.stderr)
        services = self.services()
        self.assertIn("Remote", services)
        self.assertEqual(services["Remote"]["description"], "SYD")
        self.assertEqual(services["Syncthing"]["description"], "File Synchronisation")
        self.assertIn("Shared", services)
        self.assertNotIn("Local", services)
        self.assertNotIn("Hidden", services)
        self.assertNotIn("mbk-bento", services)
        self.assertNotIn("mbk-kimbap", services)
        self.assertNotIn("mbk-hass", services)
        self.assertNotIn("mbk-gateway", services)
        self.assertEqual(services["TrueNAS"]["widget"]["type"], "truenas")

    def test_helm_widget_and_moving_an_app_between_clusters(self):
        annotations = route("Library", group="Media", **{
            "description": "Photo Manager · ${HOMEPAGE_LOCATION}",
            "widget.type": "immich",
            "widget.key": '{{ "{{HOMEPAGE_FILE_IMMICH_KEY}}" }}',
            "widget.version": "2",
            "widget.headers.X-Example": "value",
            "weight": "-100",
        })["metadata"]["annotations"]
        resource = {
            "apiVersion": "helm.toolkit.fluxcd.io/v2",
            "kind": "HelmRelease",
            "metadata": {"name": "library", "namespace": "library"},
            "spec": {"values": {"route": {"private": {"annotations": annotations}}}},
        }
        self.write_routes("syd", [resource])
        result = self.render()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.services()["Library"]["description"], "Photo Manager · SYD")
        widget = self.services()["Library"]["widget"]
        self.assertEqual(widget["key"], "{{HOMEPAGE_FILE_IMMICH_KEY}}")
        self.assertEqual(widget["headers"], {"X-Example": "value"})
        self.assertEqual(widget["version"], "2")
        self.assertIn("Media", read_yaml(self.output / "settings.yaml")["layout"])
        self.write_routes("mbk", [resource])
        self.write_routes("syd", [route("Remote")])
        result = self.render()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Library", self.services())
        self.assertIn("Media", read_yaml(self.output / "settings.yaml")["layout"])

    def test_native_machine_widgets_use_homelab_identities(self):
        import shutil

        homelab = self.directory / "homelab"
        shutil.copytree(HOMELAB, homelab)
        path = homelab / "data/machines.yaml"
        inventory = read_yaml(path)
        inventory["machines"]["mbk"]["kimbap"]["beszel"] = True
        inventory["machines"]["mbk"]["personal"] = {"platform": "macos", "management_port": 443}
        inventory["machines"]["mbk"]["sensor"] = {"platform": "slzb"}
        inventory["machines"]["mbk"]["taco"] = {"beszel": True, "cluster": "mbk", "platform": "talos", "type": "vm"}
        path.write_text(json.dumps(inventory))
        identities = self.directory / "infrastructure.json"
        identities.write_text(json.dumps({
            "cloudflare": {"account_id": "account", "tunnels": {"kimbap": "storage-tunnel", "mbk": "cluster-tunnel"}},
            "tailscale": {"kimbap": "storage-device", "taco": "node-device", "personal": "personal-device"},
        }))
        beszel = route("Beszel")
        beszel["metadata"]["namespace"] = "beszel"
        self.write_routes("mbk", [beszel])
        result = self.render(HOMELAB_DIRECTORY=str(homelab), HOMELAB_INFRASTRUCTURE_FILE=str(identities))
        self.assertEqual(result.returncode, 0, result.stderr)
        services = self.services()
        self.assertNotIn("mbk-kimbap", services)
        self.assertNotIn("mbk-sensor", services)
        groups = {name: {key: value for card in cards for key, value in card.items()}
                  for group in read_yaml(self.output / "services.yaml")
                  for name, cards in group.items()}
        self.assertNotIn("mbk-personal", groups)
        self.assertIn("Netboot", groups["Infrastructure"])
        self.assertIn("ESPHome", groups["Smart Home"])
        storage = groups["mbk-storage"]
        self.assertEqual(list(storage), ["Beszel", "Cloudflare Tunnel", "Tailscale", "TrueNAS"])
        self.assertEqual(storage["TrueNAS"]["widget"]["type"], "truenas")
        self.assertTrue(storage["TrueNAS"]["widget"]["enablePools"])
        self.assertNotIn("widgets", storage["TrueNAS"])
        node = groups["mbk-taco"]
        self.assertEqual(list(node), ["Beszel", "Cloudflare Tunnel", "Tailscale"])
        self.assertEqual(node["Beszel"]["widget"]["systemId"], "mbk-taco")
        self.assertEqual(node["Tailscale"]["widget"]["deviceid"], "node-device")
        self.assertEqual(node["Cloudflare Tunnel"]["widget"]["tunnelid"], "cluster-tunnel")
        self.assertEqual(node["Tailscale"]["widget"]["key"], "{{HOMEPAGE_FILE_TAILSCALE_KEY}}")
        self.assertEqual(node["Tailscale"]["href"], "https://login.tailscale.com/admin/machines/node-device")
        self.assertEqual(node["Beszel"]["widget"]["password"], "{{HOMEPAGE_FILE_BESZEL_PASSWORD}}")
        self.assertEqual(node["Beszel"]["widget"]["fields"], ["status", "cpu", "memory", "network"])
        self.assertEqual(node["Beszel"]["weight"], -100)
        self.assertEqual(node["Beszel"]["icon"], "beszel")
        layout = read_yaml(self.output / "settings.yaml")["layout"]
        for group in ["mbk-storage", "mbk-taco"]:
            self.assertEqual(layout[group]["tab"], "Servers")
        for group in ["Infrastructure", "Operations", "Smart Home"]:
            self.assertEqual(layout[group]["tab"], "Services")
        before = (self.output / "services.yaml").read_bytes()
        identities.write_text("{broken json")
        self.assertNotEqual(self.render(HOMELAB_DIRECTORY=str(homelab), HOMELAB_INFRASTRUCTURE_FILE=str(identities)).returncode, 0)
        self.assertEqual((self.output / "services.yaml").read_bytes(), before)

    def test_cluster_tools_follow_inventory_hosts_without_name_suffixes(self):
        import shutil

        homelab = self.directory / "homelab"
        shutil.copytree(HOMELAB, homelab)
        path = homelab / "data/machines.yaml"
        inventory = read_yaml(path)
        inventory["machines"]["mbk"]["node"] = {"cluster": "mbk", "hostname": "renamed", "type": "vm"}
        inventory["machines"]["syd"] = {"node": {"cluster": "syd", "type": "vm"}}
        path.write_text(json.dumps(inventory))
        for cluster in ("mbk", "syd"):
            tool = route("Headlamp", group="Servers", instance="inventory")
            tool["metadata"]["namespace"] = "headlamp"
            self.write_routes(cluster, [tool])
        result = self.render(HOMELAB_DIRECTORY=str(homelab))
        self.assertEqual(result.returncode, 0, result.stderr)
        groups = {name: cards for group in read_yaml(self.output / "services.yaml") for name, cards in group.items()}
        local = groups["mbk-renamed"][0]["Headlamp"]
        remote = groups["syd-node"][0]["Headlamp"]
        self.assertEqual(local["namespace"], "headlamp")
        self.assertEqual(local["app"], "headlamp")
        self.assertNotIn("namespace", remote)
        layout = read_yaml(self.output / "settings.yaml")["layout"]
        self.assertEqual(layout["mbk-renamed"]["tab"], "Servers")
        self.assertEqual(layout["syd-node"]["tab"], "Servers")
        self.assertNotIn("Servers", layout)
        before = (self.output / "services.yaml").read_bytes()
        inventory["machines"]["mbk"]["extra"] = {"cluster": "mbk", "type": "vm"}
        path.write_text(json.dumps(inventory))
        self.assertNotEqual(self.render(HOMELAB_DIRECTORY=str(homelab)).returncode, 0)
        self.assertEqual((self.output / "services.yaml").read_bytes(), before)

    def test_unchanged_refresh_and_invalid_input_preserve_files(self):
        result = self.render()
        self.assertEqual(result.returncode, 0, result.stderr)
        before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.output.iterdir()}
        result = self.render()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(before, {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.output.iterdir()})
        (self.directory / "apps/overlays/syd/routes.yaml").write_text("[broken yaml\n")
        self.assertNotEqual(self.render().returncode, 0)
        self.assertEqual(before, {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.output.iterdir()})


if __name__ == "__main__":
    unittest.main()
