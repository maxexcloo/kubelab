"""Check Homepage's remote annotations and inventory refresh without network access."""

import json
import os
import shutil
import subprocess
import tarfile
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
            "namespace": name.lower(),
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

    def test_applied_revision_cache_and_failed_download_preserve_configuration(self):
        revision_file = self.directory / "revision"
        downloads = self.directory / "downloads"
        archive = self.directory / "snapshot.tar.gz"
        cache = self.directory / "cache"
        commands = self.directory / "commands"
        commands.mkdir()
        kubectl = commands / "kubectl"
        kubectl.write_text("""#!/bin/sh
if [ "$1" = --namespace ]; then
  cat "$REVISION_FIXTURE"
else
  exec "$REAL_KUBECTL" "$@"
fi
""")
        wget = commands / "wget"
        wget.write_text("""#!/bin/sh
printf '%s\n' "$6" >> "$DOWNLOAD_FIXTURE"
[ "${FAIL_DOWNLOAD:-false}" != true ] || exit 1
cp "$ARCHIVE_FIXTURE" "$2"
""")
        for command in (kubectl, wget):
            command.chmod(0o755)
        environment = {
            "ARCHIVE_FIXTURE": str(archive),
            "DOWNLOAD_FIXTURE": str(downloads),
            "HOMEPAGE_CACHE_DIRECTORY": str(cache),
            "KUBECTL": str(kubectl),
            "KUBELAB_DIRECTORY": "",
            "PATH": str(commands) + os.pathsep + os.environ["PATH"],
            "REAL_KUBECTL": shutil.which("kubectl"),
            "REVISION_FIXTURE": str(revision_file),
        }

        def snapshot():
            with tarfile.open(archive, "w:gz") as output:
                for directory in ("apps", "clusters"):
                    output.add(self.directory / directory, arcname="snapshot/" + directory)

        first = "a" * 40
        second = "b" * 40
        revision_file.write_text("main@sha1:" + first)
        snapshot()
        result = self.render(**environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Local", self.services())
        self.assertEqual(downloads.read_text().splitlines(), [
            "https://codeload.github.com/maxexcloo/kubelab/tar.gz/" + first,
        ])
        self.write_routes("mbk", [route("Future")])
        snapshot()
        result = self.render(**environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Local", self.services())
        self.assertNotIn("Future", self.services())
        self.assertEqual(len(downloads.read_text().splitlines()), 1)
        revision_file.write_text("main@sha1:" + second)
        result = self.render(**environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Future", self.services())
        self.assertNotIn("Local", self.services())
        self.assertEqual(downloads.read_text().splitlines()[-1],
                         "https://codeload.github.com/maxexcloo/kubelab/tar.gz/" + second)
        before = {p.name: p.read_bytes() for p in self.output.iterdir()}
        revision_file.write_text("main@sha1:" + "c" * 40)
        self.assertNotEqual(self.render(**(environment | {"FAIL_DOWNLOAD": "true"})).returncode, 0)
        self.assertEqual((cache / "revision").read_text().strip(), second)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.output.iterdir()})
        revision_file.write_text("main@sha1:invalid")
        self.assertNotEqual(self.render(**environment).returncode, 0)
        self.assertEqual(len(downloads.read_text().splitlines()), 3)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.output.iterdir()})

    def test_mini_apps_follow_cluster_selection_and_homepage_annotations(self):
        mini_apps = self.directory / "mini-apps"
        for cluster, name in (("mbk", "Budget"), ("syd", "Feeds")):
            directory = mini_apps / "clusters" / cluster
            directory.mkdir(parents=True)
            (directory / "kustomization.yaml").write_text("resources: [app.yaml]\n")
            (directory / "app.yaml").write_text(json.dumps(route(name)))
            source = {
                "apiVersion": "source.toolkit.fluxcd.io/v1", "kind": "GitRepository",
                "metadata": {"name": "mini-apps", "namespace": "flux-system"},
                "spec": {"url": "https://github.com/example/mini-apps.git", "ref": {"branch": "deploy"}},
            }
            selection = {
                "apiVersion": "kustomize.toolkit.fluxcd.io/v1", "kind": "Kustomization",
                "metadata": {"name": "mini-apps", "namespace": "flux-system"},
                "spec": {"path": f"./clusters/{cluster}"},
            }
            self.write_routes(cluster, [route("Existing"), selection, source])
        result = self.render(MINI_APPS_DIRECTORY=str(mini_apps))
        self.assertEqual(result.returncode, 0, result.stderr)
        services = self.services()
        self.assertIn("Budget", services)
        self.assertIn("Feeds", services)
        self.assertIn("Existing", services)
        self.assertEqual(services["Feeds"]["href"], "https://feeds.example.net")
        groups = {name: cards for group in read_yaml(self.output / "services.yaml") for name, cards in group.items()}
        self.assertEqual([next(iter(card)) for card in groups["Mini Apps"]], ["Budget", "Feeds"])
        self.assertNotIn("Feeds", [next(iter(card)) for card in groups["Applications"]])
        self.assertEqual(read_yaml(self.output / "settings.yaml")["layout"]["Mini Apps"]["tab"], "Services")
        # Newly deployed apps appear on refresh; removed apps disappear without
        # maintaining a second list of dashboard cards.
        path = mini_apps / "clusters/syd/app.yaml"
        path.write_text(json.dumps(route("New Tool")))
        self.assertEqual(self.render(MINI_APPS_DIRECTORY=str(mini_apps)).returncode, 0)
        self.assertIn("New Tool", self.services())
        self.assertNotIn("Feeds", self.services())
        before = (self.output / "services.yaml").read_bytes()
        (mini_apps / "clusters/syd/app.yaml").unlink()
        self.assertNotEqual(self.render(MINI_APPS_DIRECTORY=str(mini_apps)).returncode, 0)
        self.assertEqual((self.output / "services.yaml").read_bytes(), before)

    def test_remote_annotations_and_external_machines(self):
        result = self.render()
        self.assertEqual(result.returncode, 0, result.stderr)
        services = self.services()
        self.assertIn("Remote", services)
        self.assertEqual(services["Remote"]["description"], "")
        self.assertEqual(services["Syncthing"]["description"], "File Synchronisation")
        self.assertIn("Shared", services)
        self.assertIn("Local", services)
        self.assertNotIn("siteMonitor", services["Local"])
        self.assertEqual(services["Remote"]["siteMonitor"], services["Remote"]["href"])
        self.assertNotIn("Hidden", services)
        self.assertNotIn("mbk-bento", services)
        self.assertNotIn("mbk-kimbap", services)
        self.assertNotIn("mbk-hass", services)
        self.assertNotIn("mbk-gateway", services)
        self.assertEqual(services["TrueNAS"]["widget"]["type"], "truenas")
        self.assertEqual(list(read_yaml(self.output / "settings.yaml")["layout"])[-1], "Providers")

    def test_helm_widget_and_moving_an_app_between_clusters(self):
        annotations = route("Library", group="Media", **{
            "description": "Photo Manager",
            "widget.type": "immich",
            "widget.key": '{{ "{{HOMEPAGE_FILE_IMMICH_KEY}}" }}',
            "widget.version": "2",
            "widget.headers.X-Example": "value",
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
        groups = {name: cards for group in read_yaml(self.output / "services.yaml") for name, cards in group.items()}
        self.assertEqual(groups["Media"][0]["Library"]["description"], "Photo Manager • SYD")
        self.assertEqual(groups["Cluster: SYD"][0]["Library"]["description"], "Photo Manager")
        widget = self.services()["Library"]["widget"]
        self.assertEqual(widget["key"], "{{HOMEPAGE_FILE_IMMICH_KEY}}")
        self.assertEqual(widget["headers"], {"X-Example": "value"})
        self.assertEqual(widget["version"], 2)
        self.assertIn("Media", read_yaml(self.output / "settings.yaml")["layout"])
        self.write_routes("mbk", [resource])
        self.write_routes("syd", [route("Remote")])
        result = self.render()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Library", self.services())
        groups = {name: cards for group in read_yaml(self.output / "services.yaml") for name, cards in group.items()}
        self.assertEqual(groups["Media"][0]["Library"]["description"], "Photo Manager • MBK")
        self.assertIn("Library", groups["Cluster: MBK"][0])
        self.assertIn("Media", read_yaml(self.output / "settings.yaml")["layout"])

    def test_native_machine_widgets_use_homelab_identities(self):
        import shutil

        homelab = self.directory / "homelab"
        shutil.copytree(HOMELAB, homelab)
        path = homelab / "data/machines.yaml"
        inventory = read_yaml(path)
        del inventory["machines"]["mbk"]["kimbap"]["services"]["syncthing"]
        inventory["machines"]["mbk"]["kimbap"]["beszel"] = True
        inventory["machines"]["mbk"]["personal"] = {"platform": "macos", "services": {"management": {"port": 443, "scheme": "https"}}}
        inventory["machines"]["mbk"]["sensor"] = {"platform": "slzb"}
        inventory["machines"]["mbk"]["taco"] = {"beszel": True, "cluster": "mbk", "platform": "talos", "type": "vm"}
        path.write_text(json.dumps(inventory))
        providers_path = homelab / "data/providers.yaml"
        providers = read_yaml(providers_path)
        providers["providers"].update({
            "cloudflare": {
                "description": "Cloudflare Tunnel", "icon": "cloudflare", "name": "Cloudflare Tunnel",
                "widget": {"type": "cloudflared", "key": "{{HOMEPAGE_FILE_CLOUDFLARE_KEY}}"},
            },
            "tailscale": {
                "description": "VPN", "icon": "tailscale", "name": "Tailscale",
                "widget": {"type": "tailscale", "key": "{{HOMEPAGE_FILE_TAILSCALE_KEY}}"},
            },
        })
        for name in ("Cloudflare", "Tailscale"):
            providers["providers"][name.lower()].update({"name": name, "description": name, "icon": name.lower(), "url": f"https://{name.lower()}.example.net"})
        providers_path.write_text(json.dumps(providers))
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
        self.assertIn("Home Assistant", groups["Smart Home"])
        self.assertEqual(groups["Smart Home"]["Home Assistant"]["widget"], groups["mbk-hass"]["Home Assistant"]["widget"])
        self.assertEqual(groups["Smart Home"]["Home Assistant"]["description"], "Smart Home & Automations • HASS (MBK)")
        self.assertEqual(groups["Infrastructure"]["Syncthing"]["widget"]["url"], "https://syncthing.excloo.com")
        storage = groups["mbk-storage"]
        self.assertEqual(list(storage), ["Beszel", "Cloudflare", "Tailscale", "TrueNAS", "Netboot"])
        self.assertEqual(storage["TrueNAS"]["widget"]["type"], "truenas")
        self.assertTrue(storage["TrueNAS"]["widget"]["enablePools"])
        self.assertNotIn("widgets", storage["TrueNAS"])
        node = groups["mbk-taco"]
        self.assertEqual(list(node), ["Beszel", "Tailscale"])
        self.assertEqual(node["Beszel"]["widget"]["systemId"], "mbk-taco")
        self.assertEqual(node["Beszel"]["href"], "https://beszel.example.net/system/mbk-taco")
        self.assertEqual(node["Tailscale"]["widget"]["deviceid"], "node-device")
        self.assertEqual(groups["Cluster: MBK"]["Cloudflare"]["widget"]["tunnelid"], "cluster-tunnel")
        self.assertEqual(node["Tailscale"]["widget"]["key"], "{{HOMEPAGE_FILE_TAILSCALE_KEY}}")
        self.assertEqual(node["Tailscale"]["href"], "https://login.tailscale.com/admin/machines/node-device")
        self.assertEqual(node["Beszel"]["widget"]["password"], "{{HOMEPAGE_FILE_BESZEL_PASSWORD}}")
        self.assertEqual(node["Beszel"]["widget"]["fields"], ["status", "cpu", "memory", "network"])
        self.assertEqual(node["Beszel"]["weight"], -100)
        self.assertEqual(node["Beszel"]["icon"], "sh-beszel")
        layout = read_yaml(self.output / "settings.yaml")["layout"]
        for group in ["mbk-storage", "mbk-taco"]:
            self.assertEqual(layout[group]["tab"], "Servers")
        for group in ["Infrastructure", "Operations", "Smart Home"]:
            self.assertEqual(layout[group]["tab"], "Services")
        before = (self.output / "services.yaml").read_bytes()
        identities.write_text("{broken json")
        self.assertNotEqual(self.render(HOMELAB_DIRECTORY=str(homelab), HOMELAB_INFRASTRUCTURE_FILE=str(identities)).returncode, 0)
        self.assertEqual((self.output / "services.yaml").read_bytes(), before)

    def test_management_services_share_schema_and_do_not_change_other_cards(self):
        import shutil

        homelab = self.directory / "homelab"
        shutil.copytree(HOMELAB, homelab)
        path = homelab / "data/machines.yaml"
        with path.open("a") as inventory:
            inventory.write("""  lab:
    first:
      beszel: true
      platform: ucore
      type: server
      services:
        management:
          description: Host Administration
          icon: example-console
          name: Example Console
          port: 9090
          scheme: https
    second:
      hostname: renamed
      platform: bazzite
      type: server
      services:
        management:
          description: Host Administration
          icon: example-console
          name: Example Console
          port: 9443
          scheme: https
""")
        beszel = route("Beszel")
        beszel["metadata"]["namespace"] = "beszel"
        self.write_routes("mbk", [beszel])
        result = self.render(HOMELAB_DIRECTORY=str(homelab))
        self.assertEqual(result.returncode, 0, result.stderr)
        groups = {name: {key: value for card in cards for key, value in card.items()}
                  for group in read_yaml(self.output / "services.yaml") for name, cards in group.items()}
        for host, endpoint in [("first", "first.lab.example.net:9090"), ("renamed", "renamed.lab.example.net:9443")]:
            panel = groups[f"lab-{host}"]["Example Console"]
            self.assertEqual(panel["href"], f"https://{endpoint}")
            self.assertEqual(panel["description"], "Host Administration")
            self.assertEqual(panel["icon"], "example-console")
        self.assertEqual(groups["lab-first"]["Beszel"]["icon"], "sh-beszel")
        self.assertEqual(groups["lab-first"]["Beszel"]["description"], "System Monitoring")
        self.assertEqual(groups["Infrastructure"]["Netboot"]["href"], "http://storage.mbk.example.net:31010")
        self.assertEqual(groups["mbk-storage"]["TrueNAS"]["widget"]["type"], "truenas")

    def test_cluster_tools_support_multiple_nodes_without_inventing_placement(self):
        import shutil

        homelab = self.directory / "homelab"
        shutil.copytree(HOMELAB, homelab)
        path = homelab / "data/machines.yaml"
        inventory = read_yaml(path)
        del inventory["machines"]["mbk"]["taco"]
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
        local = groups["Cluster: MBK"][0]["Headlamp"]
        remote = groups["Cluster: SYD"][0]["Headlamp"]
        self.assertEqual(local["namespace"], "headlamp")
        self.assertEqual(local["app"], "headlamp")
        self.assertNotIn("namespace", remote)
        layout = read_yaml(self.output / "settings.yaml")["layout"]
        self.assertEqual(layout["Cluster: MBK"]["tab"], "Servers")
        self.assertEqual(layout["Cluster: SYD"]["tab"], "Servers")
        self.assertNotIn("Servers", layout)
        before = (self.output / "services.yaml").read_bytes()
        inventory["machines"]["mbk"]["extra"] = {"cluster": "mbk", "type": "vm"}
        path.write_text(json.dumps(inventory))
        self.assertEqual(self.render(HOMELAB_DIRECTORY=str(homelab)).returncode, 0)
        self.assertEqual((self.output / "services.yaml").read_bytes(), before)

    def test_native_node_widget_and_local_pod_stats_follow_cluster_selection(self):
        self.write_routes("mbk", [route("Local", **{"pod-selector": "app=local"}),
                                  route("Compact", showStats="false")])
        for cluster in ("mbk", "syd"):
            with self.subTest(cluster=cluster):
                result = self.render(HOMEPAGE_CLUSTER=cluster)
                self.assertEqual(result.returncode, 0, result.stderr)
                widgets = read_yaml(self.output / "widgets.yaml")
                kubernetes = next(widget["kubernetes"] for widget in widgets if "kubernetes" in widget)
                self.assertEqual(kubernetes["cluster"]["label"], f"Cluster: {cluster.upper()}")
                for scope in ("cluster", "nodes"):
                    for option in ("cpu", "memory", "show", "showLabel"):
                        self.assertIs(kubernetes[scope][option], True)
                # Nodes are discovered by Homepage, never copied from host inventory.
                self.assertEqual(set(kubernetes), {"cluster", "nodes"})
                services = self.services()
                local, remote = ("Local", "Remote") if cluster == "mbk" else ("Remote", "Local")
                self.assertIs(services[local]["showStats"], True)
                self.assertEqual(services[local]["namespace"], local.lower())
                for option in ("app", "namespace", "podSelector", "showStats"):
                    self.assertNotIn(option, services[remote])
                if cluster == "mbk":
                    self.assertEqual(services[local]["podSelector"], "app=local")
                    self.assertIs(services["Compact"]["showStats"], False)
                layout = read_yaml(self.output / "settings.yaml")["layout"]
                self.assertEqual(layout[f"Cluster: {cluster.upper()}"]["tab"], "Servers")

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
