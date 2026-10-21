"""Check Homepage dashboard composition without network access."""

import shutil
import unittest

from homepage_support import HOMELAB, HomepageDashboardFixture, beszel_route, route
from support import read_yaml


class HomepageDashboardTests(HomepageDashboardFixture, unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
