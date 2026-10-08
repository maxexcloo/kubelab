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
        self.assertIn("Shared (SYD)", services)
        self.assertNotIn("Local", services)
        self.assertNotIn("Shared", services)
        self.assertNotIn("Hidden", services)
        self.assertEqual(services["mbk-bento"]["href"], "https://bento.mbk.example.net:9090")
        self.assertNotIn("siteMonitor", services["mbk-bento"])
        self.assertNotIn("mbk-kimbap", services)
        self.assertNotIn("mbk-hass", services)
        self.assertNotIn("mbk-gateway", services)
        self.assertNotIn("widget", services["TrueNAS"])

    def test_helm_widget_and_moving_an_app_between_clusters(self):
        annotations = route("Library", group="Media", **{
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
        inventory["machines"]["mbk"]["sensor"] = {"platform": "slzb"}
        inventory["machines"]["mbk"]["taco"] = {"beszel": True, "cluster": "mbk", "platform": "talos"}
        path.write_text(json.dumps(inventory))
        identities = self.directory / "infrastructure.json"
        identities.write_text(json.dumps({
            "cloudflare": {"account_id": "account", "tunnels": {"kimbap": "storage-tunnel", "mbk": "cluster-tunnel"}},
            "tailscale": {"kimbap": "storage-device", "taco": "node-device"},
        }))
        beszel = route("Beszel")
        beszel["metadata"]["namespace"] = "beszel"
        self.write_routes("mbk", [beszel])
        result = self.render(HOMELAB_DIRECTORY=str(homelab), HOMELAB_INFRASTRUCTURE_FILE=str(identities))
        self.assertEqual(result.returncode, 0, result.stderr)
        services = self.services()
        self.assertNotIn("mbk-kimbap", services)
        self.assertNotIn("mbk-sensor", services)
        self.assertNotIn("widget", services["TrueNAS"])
        self.assertEqual([widget["type"] for widget in services["TrueNAS"]["widgets"]],
                         ["beszel"])
        node = services["mbk-taco"]
        self.assertEqual(node["widgets"][0]["systemId"], "mbk-taco")
        self.assertEqual(len(node["widgets"]), 1)
        self.assertEqual(node["href"], "https://login.tailscale.com/admin/machines/node-device")
        self.assertEqual(node["widgets"][0]["password"], "{{HOMEPAGE_FILE_BESZEL_PASSWORD}}")
        self.assertEqual(node["weight"], -100)
        self.assertEqual(node["icon"], "talos")
        self.assertEqual(services["mbk-bento"]["weight"], 0)
        before = (self.output / "services.yaml").read_bytes()
        identities.write_text("{broken json")
        self.assertNotEqual(self.render(HOMELAB_DIRECTORY=str(homelab), HOMELAB_INFRASTRUCTURE_FILE=str(identities)).returncode, 0)
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
