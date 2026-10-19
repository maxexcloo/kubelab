"""Check Homepage's remote annotations and inventory refresh without network access."""

import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

from support import ROOT, read_yaml

APP = ROOT / "apps/base/homepage"
HOMELAB = ROOT / "tests/fixtures/homepage/homelab"


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



def beszel_route():
    beszel = route("Beszel", description="System Monitoring", icon="sh-beszel", **{
        "widget.password": '{{ "{{HOMEPAGE_VAR_BESZEL_PASSWORD}}" }}', "widget.type": "beszel",
        "widget.url": "https://beszel.example.net",
        "widget.username": '{{ "{{HOMEPAGE_VAR_BESZEL_USERNAME}}" }}', "widget.version": "2"})
    beszel["metadata"]["namespace"] = "beszel"
    return beszel

class HomepageDashboardTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.output = self.directory / "output"
        self.placements = self.directory / "placements.json"
        self.placements.write_text("{}")
        self.queries = self.directory / "queries.jsonl"
        self.gatus = self.directory / "gatus.json"
        self.gatus.write_text(json.dumps([
            {"group": "Providers", "key": "providers_example", "name": "Example",
             "results": [{"duration": 12000000, "success": True}]},
        ]))
        self.kubectl = self.directory / "kubectl"
        self.kubectl.write_text("""#!/usr/bin/env python3
import json
import os
import sys
if sys.argv[1:2] == ["--namespace"] and sys.argv[3:5] == ["get", "pods"]:
    with open(os.environ["POD_QUERIES"], "a") as output:
        output.write(json.dumps(sys.argv[1:]) + "\\n")
    with open(os.environ["POD_PLACEMENTS"]) as source:
        placements = json.load(source)
        nodes = placements.get(sys.argv[2] + "/" + sys.argv[-1], placements.get(sys.argv[2], ["node"]))
    if nodes == "fail":
        sys.exit(1)
    print("\\n".join(nodes))
else:
    os.execv(os.environ["SYSTEM_KUBECTL"], [os.environ["SYSTEM_KUBECTL"], *sys.argv[1:]])
""")
        self.kubectl.chmod(0o755)
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
                "HOMELAB_INFRASTRUCTURE_FILE": str(ROOT / "tests/fixtures/homepage/infrastructure.json"),
                "HOMEPAGE_CLUSTER": "mbk",
                "HOMEPAGE_GATUS_STATUSES_FILE": str(self.gatus),
                "HOMEPAGE_ROUTE_SCRIPT": str(ROOT / "scripts/service-routes/service_routes.yq"),
                "KUBELAB_DIRECTORY": str(self.directory),
                "KUBECTL": str(self.kubectl),
                "POD_PLACEMENTS": str(self.placements),
                "POD_QUERIES": str(self.queries),
                "REAL_KUBECTL": shutil.which("kubectl"),
                "SYSTEM_KUBECTL": shutil.which("kubectl"),
            } | environment,
            capture_output=True,
            text=True,
        )

    def groups(self, tab=None):
        groups = read_yaml(self.output / "services.yaml")
        if tab is not None:
            groups = next(group[tab] for group in groups if tab in group)
            if groups and not isinstance(next(iter(groups[0].values())), list):
                groups = [{tab: groups}]

        def leaves(groups):
            for group in groups:
                for name, cards in group.items():
                    if cards and isinstance(next(iter(cards[0].values())), list):
                        yield from leaves(cards)
                    else:
                        yield name, cards

        return dict(leaves(groups))

    def services(self):
        return {
            name: service
            for entries in self.groups().values()
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
if [ "$3" = get ] && [ "$4" = kustomization ]; then
  cat "$REVISION_FIXTURE"
elif [ "$3" = get ] && [ "$4" = gitrepository ] && [ "$5" = flux-system ]; then
  printf 'https://github.com/example/kubelab.git'
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
            "REAL_KUBECTL": str(self.kubectl),
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
            "https://codeload.github.com/example/kubelab/tar.gz/" + first,
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
                         "https://codeload.github.com/example/kubelab/tar.gz/" + second)
        before = {p.name: p.read_bytes() for p in self.output.iterdir()}
        revision_file.write_text("main@sha1:" + "c" * 40)
        self.assertNotEqual(self.render(**(environment | {"FAIL_DOWNLOAD": "true"})).returncode, 0)
        self.assertEqual((cache / "revision").read_text().strip(), second)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.output.iterdir()})
        revision_file.write_text("main@sha1:invalid")
        self.assertNotEqual(self.render(**environment).returncode, 0)
        self.assertEqual(len(downloads.read_text().splitlines()), 3)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.output.iterdir()})

    def test_minilab_follow_cluster_selection_and_homepage_annotations(self):
        minilab = self.directory / "minilab"
        for cluster, name in (("mbk", "Budget"), ("syd", "Feeds")):
            directory = minilab / "clusters" / cluster
            directory.mkdir(parents=True)
            (directory / "kustomization.yaml").write_text("resources: [app.yaml]\n")
            app = route(f"Minilab: {name}", href=f"https://{name.lower()}.example.net")
            app["metadata"].update({"name": name.lower(), "namespace": name.lower()})
            (directory / "app.yaml").write_text(json.dumps(app))
            source = {
                "apiVersion": "source.toolkit.fluxcd.io/v1", "kind": "GitRepository",
                "metadata": {"name": "minilab", "namespace": "flux-system"},
                "spec": {"url": "https://github.com/example/minilab.git", "ref": {"branch": "deploy"}},
            }
            selection = {
                "apiVersion": "kustomize.toolkit.fluxcd.io/v1", "kind": "Kustomization",
                "metadata": {"name": "minilab", "namespace": "flux-system"},
                "spec": {"path": f"./clusters/{cluster}"},
            }
            self.write_routes(cluster, [route("Existing"), selection, source])
        result = self.render(MINILAB_DIRECTORY=str(minilab))
        self.assertEqual(result.returncode, 0, result.stderr)
        services = self.services()
        self.assertIn("Budget", services)
        self.assertIn("Feeds", services)
        self.assertIn("Existing", services)
        self.assertEqual(services["Feeds"]["href"], "https://feeds.example.net")
        groups = self.groups()
        self.assertEqual([next(iter(card)) for card in groups["Mini"]], ["Budget", "Feeds"])
        # Only the Home group states the source; cluster groups keep the prefix.
        self.assertIn("Minilab: Feeds", [next(iter(card)) for card in self.groups("Clusters")["syd"]])
        self.assertNotIn("Feeds", [next(iter(card)) for card in groups["Applications"]])
        self.assertEqual(read_yaml(self.output / "settings.yaml")["layout"]["Home"]["tab"], "Home")
        # Newly deployed apps appear on refresh; removed apps disappear without
        # maintaining a second list of dashboard cards.
        path = minilab / "clusters/syd/app.yaml"
        path.write_text(json.dumps(route("New Tool")))
        self.assertEqual(self.render(MINILAB_DIRECTORY=str(minilab)).returncode, 0)
        self.assertIn("New Tool", self.services())
        self.assertNotIn("Feeds", self.services())
        before = (self.output / "services.yaml").read_bytes()
        (minilab / "clusters/syd/app.yaml").unlink()
        self.assertNotEqual(self.render(MINILAB_DIRECTORY=str(minilab)).returncode, 0)
        self.assertEqual((self.output / "services.yaml").read_bytes(), before)

    def test_required_inputs_fail_without_publishing(self):
        for name in ("HOMELAB_INFRASTRUCTURE_FILE", "HOMEPAGE_ROUTE_SCRIPT", "KUBECTL"):
            with self.subTest(name=name):
                result = self.render(**{name: ""})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f"{name} is required", result.stderr)
                self.assertFalse(self.output.exists())

    def test_remote_annotations_and_external_machines(self):
        result = self.render()
        self.assertEqual(result.returncode, 0, result.stderr)
        services = self.services()
        self.assertIn("Remote", services)
        self.assertEqual(services["Remote"]["description"], "syd")
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
        self.assertEqual(list(read_yaml(self.output / "settings.yaml")["layout"])[-1], "Servers")

    def test_helm_widget_and_moving_an_app_between_clusters(self):
        annotations = route("Library", group="Media", **{
            "description": "Photo Manager",
            "widget.type": "immich",
            "widget.fields": '["photos", "videos"]',
            "widget.key": '{{ "{{HOMEPAGE_VAR_IMMICH_API_KEY}}" }}',
            "widget.version": "2",
            "widget.headers.X-Example": "value",
        })["metadata"]["annotations"]
        resource = {
            "apiVersion": "helm.toolkit.fluxcd.io/v2",
            "kind": "HelmRelease",
            "metadata": {"name": "library", "namespace": "library"},
            "spec": {"values": {"route": {"private": {
                "annotations": annotations,
                "labels": {"app.kubernetes.io/name": "{{ .Release.Name }}"},
            }}}},
        }
        self.write_routes("syd", [resource])
        result = self.render()
        self.assertEqual(result.returncode, 0, result.stderr)
        groups = self.groups()
        self.assertEqual(groups["Media"][0]["Library"]["description"], "Photo Manager • syd")
        self.assertEqual(groups["syd"][0]["Library"]["description"], "Photo Manager")
        # Clusters cards show placement only, four to a row; widgets stay on Home.
        self.assertNotIn("widget", groups["syd"][0]["Library"])
        self.assertEqual(read_yaml(self.output / "settings.yaml")["layout"]["Clusters"]["syd"]["columns"], 4)
        # Home widgets move to Overview, which leads Home; categories stay compact.
        self.assertNotIn("widget", groups["Media"][0]["Library"])
        overview = {name: card for entry in groups["Overview"] for name, card in entry.items()}
        self.assertEqual(overview["Library"]["description"], "Photo Manager • syd")
        layout = read_yaml(self.output / "settings.yaml")["layout"]["Home"]
        self.assertEqual([key for key in layout if isinstance(layout[key], dict)][0], "Overview")
        self.assertEqual(layout["Media"]["columns"], 4)
        widget = overview["Library"]["widget"]
        self.assertEqual(widget["fields"], ["photos", "videos"])
        self.assertEqual(widget["key"], "{{HOMEPAGE_VAR_IMMICH_API_KEY}}")
        self.assertEqual(widget["headers"], {"X-Example": "value"})
        self.assertEqual(widget["version"], 2)
        self.assertIn("Media", read_yaml(self.output / "settings.yaml")["layout"]["Home"])
        self.write_routes("mbk", [resource])
        self.write_routes("syd", [route("Remote")])
        result = self.render()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Library", self.services())
        self.assertEqual(self.services()["Library"]["app"], "library")
        groups = self.groups()
        self.assertEqual(groups["Media"][0]["Library"]["description"], "Photo Manager • mbk/node")
        self.assertIn("Library", groups["mbk/node"][0])
        self.assertIn("Media", read_yaml(self.output / "settings.yaml")["layout"]["Home"])

    def test_helm_status_selector_uses_explicit_release_name_for_both_route_layouts(self):
        annotations = route("Reader")["metadata"]["annotations"]
        route_values = {
            "annotations": annotations,
            "labels": {"app.kubernetes.io/name": "{{ .Release.Name }}"},
        }
        for routes in (dict(route_values, apiVersion="gateway.networking.k8s.io/v1"), {"private": route_values}):
            with self.subTest(routes=routes):
                self.write_routes("mbk", [{
                    "apiVersion": "helm.toolkit.fluxcd.io/v2",
                    "kind": "HelmRelease",
                    "metadata": {"name": "application", "namespace": "reader"},
                    "spec": {"releaseName": "miniflux", "values": {"route": routes}},
                }])
                result = self.render()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.services()["Reader"]["app"], "miniflux")

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
                "widget": {"type": "cloudflared", "key": "{{HOMEPAGE_VAR_CLOUDFLARE_API_TOKEN}}"},
            },
            "tailscale": {
                "description": "VPN", "icon": "tailscale", "name": "Tailscale",
                "widget": {"type": "tailscale", "key": "{{HOMEPAGE_VAR_TAILSCALE_API_TOKEN}}"},
            },
        })
        for name in ("Cloudflare", "Tailscale"):
            providers["providers"][name.lower()].update({"name": name, "description": name, "icon": name.lower(), "url": f"https://{name.lower()}.example.net"})
        providers_path.write_text(json.dumps(providers))
        identities = self.directory / "infrastructure.json"
        identities.write_text(json.dumps({
            "cloudflare": {"account_id": "account", "tunnels": {"kimbap": "storage-tunnel", "mbk": "cluster-tunnel"}},
            "tailscale": {"kimbap": "storage-device", "mbk": "cluster-device", "taco": "node-device", "personal": "personal-device"},
        }))
        beszel = beszel_route()
        self.write_routes("mbk", [beszel])
        result = self.render(HOMELAB_DIRECTORY=str(homelab), HOMELAB_INFRASTRUCTURE_FILE=str(identities))
        self.assertEqual(result.returncode, 0, result.stderr)
        services = self.services()
        self.assertNotIn("mbk-kimbap", services)
        self.assertNotIn("mbk-sensor", services)
        groups = {name: {key: value for card in cards for key, value in card.items()}
                  for name, cards in self.groups().items()}
        self.assertNotIn("mbk-personal", groups)
        self.assertIn("Netboot", groups["Infrastructure"])
        self.assertIn("ESPHome", groups["Smart Home"])
        self.assertIn("Home Assistant", groups["Smart Home"])
        self.assertNotIn("widget", groups["Smart Home"]["Home Assistant"])
        self.assertEqual(groups["Overview"]["Home Assistant"]["widget"], groups["mbk-hass"]["Home Assistant"]["widget"])
        # Taller cards end the Overview grid: TrueNAS adds pool rows to its widget.
        self.assertEqual(list(groups["Overview"])[-1], "TrueNAS")
        self.assertEqual(groups["Smart Home"]["Home Assistant"]["description"], "Smart Home & Automations • mbk-hass")
        storage = groups["mbk-storage"]
        # Larger cards lead: TrueNAS adds pool rows to its widget.
        self.assertEqual(list(storage), ["TrueNAS", "Beszel", "Cloudflare", "Tailscale"])
        self.assertEqual(storage["TrueNAS"]["widget"]["type"], "truenas")
        self.assertTrue(storage["TrueNAS"]["widget"]["enablePools"])
        self.assertNotIn("widgets", storage["TrueNAS"])
        node = groups["mbk-taco"]
        self.assertEqual(list(node), ["Beszel", "Tailscale"])
        self.assertEqual(node["Beszel"]["widget"]["systemId"], "mbk-taco")
        self.assertEqual(node["Beszel"]["href"], "https://beszel.example.net/system/mbk-taco")
        self.assertEqual(node["Tailscale"]["widget"]["deviceid"], "node-device")
        self.assertEqual(groups["mbk"]["Cloudflare"]["widget"]["tunnelid"], "cluster-tunnel")
        self.assertEqual(groups["mbk"]["Tailscale"]["widget"]["deviceid"], "cluster-device")
        self.assertEqual(node["Tailscale"]["widget"]["key"], "{{HOMEPAGE_VAR_TAILSCALE_API_TOKEN}}")
        self.assertEqual(node["Tailscale"]["href"], "https://login.tailscale.com/admin/machines/node-device")
        self.assertEqual(node["Beszel"]["widget"]["password"], "{{HOMEPAGE_VAR_BESZEL_PASSWORD}}")
        self.assertEqual(node["Beszel"]["widget"]["fields"], ["status", "cpu", "memory", "network"])
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
        beszel = beszel_route()
        self.write_routes("mbk", [beszel])
        result = self.render(HOMELAB_DIRECTORY=str(homelab))
        self.assertEqual(result.returncode, 0, result.stderr)
        groups = {name: {key: value for card in cards for key, value in card.items()}
                  for name, cards in self.groups().items()}
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
        self.write_routes("mbk", [route("Local", **{"pod-selector": "app=local"}),
                                  route("Compact", showStats="false")])
        for cluster in ("mbk", "syd"):
            with self.subTest(cluster=cluster):
                result = self.render(HOMEPAGE_CLUSTER=cluster)
                self.assertEqual(result.returncode, 0, result.stderr)
                widgets = read_yaml(self.output / "widgets.yaml")
                kubernetes = next(widget["kubernetes"] for widget in widgets if "kubernetes" in widget)
                self.assertEqual(kubernetes["cluster"]["label"], cluster)
                self.assertIn(f'--homepage-cluster: "{cluster}"', (self.output / "custom.css").read_text())
                for scope in ("cluster", "nodes"):
                    for option in ("cpu", "memory", "show", "showLabel"):
                        self.assertIs(kubernetes[scope][option], True)
                # Nodes are discovered by Homepage, never copied from host inventory.
                self.assertEqual(set(kubernetes), {"cluster", "nodes"})
                services = self.services()
                local, remote = ("Local", "Remote") if cluster == "mbk" else ("Remote", "Local")
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
        self.write_routes("mbk", [route("Reader", **{"pod-selector": "app in (reader,feeds)"}),
                                  route("Waiting")])
        self.placements.write_text(json.dumps({"reader": ["hsp", "kimbap", "hsp"], "waiting": []}))
        result = self.render()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(set(self.groups("Clusters")), {"mbk/hsp", "mbk/kimbap", "mbk/unscheduled", "syd"})
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

    def test_placement_queries_share_only_identical_namespaces_and_selectors(self):
        resources = [route("Reader", **{"pod-selector": "app in (reader,feeds)"}),
                     route("Copy", **{"pod-selector": "app in (reader,feeds)"}),
                     route("Other", **{"pod-selector": "app=other"}),
                     route("Separate", **{"pod-selector": "app in (reader,feeds)"})]
        for resource in resources[:3]:
            resource["metadata"]["namespace"] = "reader"
        self.write_routes("mbk", resources)
        self.placements.write_text(json.dumps({
            "reader/app in (reader,feeds)": ["first"],
            "reader/app=other": ["second"],
            "separate/app in (reader,feeds)": ["third"],
        }))
        result = self.render()
        self.assertEqual(result.returncode, 0, result.stderr)
        groups = self.groups("Clusters")
        for group, expected in [("mbk/first", {"Reader", "Copy"}),
                                ("mbk/second", {"Other"}), ("mbk/third", {"Separate"})]:
            self.assertEqual({name for card in groups[group] for name in card}, expected)
        queries = [json.loads(line) for line in self.queries.read_text().splitlines()]
        self.assertEqual(len(queries), 3)
        self.assertEqual({(query[1], query[-1]) for query in queries}, {
            ("reader", "app in (reader,feeds)"), ("reader", "app=other"),
            ("separate", "app in (reader,feeds)"),
        })

    def test_host_and_node_groups_have_distinct_names(self):
        self.write_routes("mbk", [route("Reader")])
        self.placements.write_text(json.dumps({"reader": ["storage"]}))
        self.assertEqual(self.render().returncode, 0)
        cluster = {name for card in self.groups("Clusters")["mbk/storage"] for name in card}
        server = {name for card in self.groups("Servers")["mbk-storage"] for name in card}
        self.assertEqual(cluster, {"Reader"})
        self.assertEqual(server, {"TrueNAS"})
        self.assertNotIn("Netboot", server)
        self.assertFalse(any("ESPHome" in card for cards in self.groups("Servers").values() for card in cards))

    def test_provider_widgets_discover_gatus_keys_and_dns_without_duplicate_checks(self):
        homelab = self.directory / "homelab"
        shutil.copytree(HOMELAB, homelab)
        path = homelab / "data/providers.yaml"
        providers = read_yaml(path)
        providers["providers"]["example"]["dns"] = {"name": "Example Resolver", "query-type": "A", "url": "192.0.2.53"}
        path.write_text(json.dumps(providers))
        self.gatus.write_text(json.dumps([
            {"group": "Providers", "key": "discovered_website", "name": "Example", "results": [{"success": True}]},
            # Gatus sorts category groups last behind an invisible Hangul filler.
            {"group": "\u3164Providers", "key": "discovered_dns", "name": "Example Resolver", "results": [{"success": False}]},
            {"group": "Applications", "key": "ignored", "name": "Other"},
        ]))
        result = self.render(HOMELAB_DIRECTORY=str(homelab))
        self.assertEqual(result.returncode, 0, result.stderr)
        cards = {name: value for card in self.groups("Providers")["Providers"] for name, value in card.items()}
        self.assertEqual(set(cards), {"Example", "Example Resolver"})
        self.assertEqual(cards["Example Resolver"]["description"], "DNS Resolver")
        self.assertNotEqual(cards["Example"]["description"], "DNS Resolver")
        for name, key in [("Example", "discovered_website"), ("Example Resolver", "discovered_dns")]:
            card = cards[name]
            self.assertEqual(card["icon"], "example")
            self.assertEqual(card["href"], "https://provider.example.com")
            self.assertNotIn("siteMonitor", card)
            self.assertNotIn("ping", card)
            self.assertEqual(card["widget"]["type"], "customapi")
            self.assertEqual(card["widget"]["url"], f"https://status.example.net/api/v1/endpoints/{key}/statuses?page=1&pageSize=1")
            self.assertEqual(card["widget"]["mappings"][0]["field"], "results.0.success")
            # Whole milliseconds: the number format truncates after scaling.
            self.assertEqual(card["widget"]["mappings"][1]["format"], "number")
        self.assertEqual(read_yaml(self.output / "bookmarks.yaml"), [])
        layout = read_yaml(self.output / "settings.yaml")["layout"]
        self.assertEqual(list(layout), ["Home", "Clusters", "Providers", "Servers"])
        self.assertEqual(layout["Providers"]["tab"], "Providers")
        before = (self.output / "services.yaml").read_bytes()
        self.gatus.write_text(json.dumps([
            {"group": "Providers", "key": "discovered_website", "name": "Example"},
        ]))
        self.assertNotEqual(self.render(HOMELAB_DIRECTORY=str(homelab)).returncode, 0)
        self.assertEqual((self.output / "services.yaml").read_bytes(), before)
        self.gatus.write_text('{"error": "unavailable"}')
        self.assertNotEqual(self.render(HOMELAB_DIRECTORY=str(homelab)).returncode, 0)
        self.assertEqual((self.output / "services.yaml").read_bytes(), before)

    def test_gatus_retries_partial_results_and_preserves_files_on_exhaustion(self):
        homelab = self.directory / "homelab"
        shutil.copytree(HOMELAB, homelab)
        providers_path = homelab / "data/providers.yaml"
        providers = read_yaml(providers_path)
        providers["providers"]["example"]["conditions"] = ["[STATUS] == 200"]
        providers_path.write_text(json.dumps(providers))
        commands = self.directory / "commands"
        commands.mkdir()
        requests = self.directory / "requests"
        wget = commands / "wget"
        wget.write_text('''#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path
requests = Path(os.environ["GATUS_REQUESTS"])
count = int(requests.read_text()) + 1 if requests.exists() else 1
requests.write_text(str(count))
partial = count == 1 or os.environ.get("FAIL_GATUS") == "true"
Path(sys.argv[2]).write_text(json.dumps([{"group": "Applications", "name": "Other"}])
                           if partial else Path(os.environ["GATUS_READY"]).read_text())
''')
        sleep = commands / "sleep"
        sleep.write_text("#!/bin/sh\nexit 0\n")
        for command in (wget, sleep):
            command.chmod(0o755)
        environment = {
            "GATUS_READY": str(self.gatus),
            "GATUS_REQUESTS": str(requests),
            "HOMELAB_DIRECTORY": str(homelab),
            "HOMEPAGE_GATUS_STATUSES_FILE": "",
            "PATH": str(commands) + os.pathsep + os.environ["PATH"],
        }
        result = self.render(**environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(requests.read_text(), "2")
        before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.output.iterdir()}
        result = self.render(**(environment | {"FAIL_GATUS": "true"}))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(requests.read_text(), "32")
        self.assertEqual(before, {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.output.iterdir()})

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
