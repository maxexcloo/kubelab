"""Check Homepage dashboard composition without network access."""

import shutil
import unittest

from homepage_support import HOMELAB, HomepageDashboardFixture, beszel_route, route
from support import read_yaml


class HomepageDashboardTests(HomepageDashboardFixture, unittest.TestCase):
    def test_route_annotations_and_external_machines(self):
        result = self.render()
        self.assertEqual(result.returncode, 0, result.stderr)
        services = self.services()
        self.assertIn("Shared", services)
        self.assertEqual(services["Local"]["description"], "mbk/node")
        self.assertNotIn("siteMonitor", services["Local"])
        self.assertNotIn("Hidden", services)
        for host in ("mbk-venus", "mbk-saturn", "mbk-luna", "mbk-sol"):
            self.assertNotIn(host, services)
        self.assertEqual(services["TrueNAS"]["widget"]["type"], "truenas")
        self.assertEqual(
            list(read_yaml(self.output / "settings.yaml")["layout"])[-1], "Servers"
        )

    def test_same_named_services_keep_their_locations(self):
        self.write_routes([route("TrueNAS", group="Infrastructure")])
        result = self.render()
        self.assertEqual(result.returncode, 0, result.stderr)
        names = [name for entry in self.groups()["Infrastructure"] for name in entry]
        self.assertIn("TrueNAS (mbk)", names)
        self.assertEqual(len([name for name in names if name.startswith("TrueNAS")]), 2)

    def test_route_widget_and_status_selector(self):
        library = route(
            "Library",
            group="Media",
            **{
                "description": "Photo Manager",
                "widget.type": "immich",
                "widget.fields": '["photos", "videos"]',
                "widget.key": "{{HOMEPAGE_VAR_IMMICH_API_KEY}}",
                "widget.version": "2",
                "widget.headers.X-Example": "value",
            },
        )
        library["metadata"]["labels"] = {"app.kubernetes.io/name": "photos"}
        self.write_routes([library])
        result = self.render()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.services()["Library"]["app"], "photos")
        groups = self.groups()
        self.assertEqual(
            groups["Media"][0]["Library"]["description"], "Photo Manager • mbk/node"
        )
        self.assertEqual(
            groups["mbk/node"][0]["Library"]["description"], "Photo Manager"
        )
        # Clusters cards show placement only, four to a row; widgets stay on Home.
        self.assertNotIn("widget", groups["mbk/node"][0]["Library"])
        settings = read_yaml(self.output / "settings.yaml")
        self.assertEqual(settings["layout"]["Clusters"]["mbk/node"]["columns"], 4)
        # Home widgets move to Overview, which leads Home; categories stay compact.
        self.assertNotIn("widget", groups["Media"][0]["Library"])
        overview = {
            name: card for entry in groups["Overview"] for name, card in entry.items()
        }
        layout = settings["layout"]["Home"]
        self.assertEqual(
            next(key for key in layout if isinstance(layout[key], dict)), "Overview"
        )
        self.assertEqual(layout["Media"]["columns"], 4)
        widget = overview["Library"]["widget"]
        self.assertEqual(widget["fields"], ["photos", "videos"])
        self.assertEqual(widget["key"], "{{HOMEPAGE_VAR_IMMICH_API_KEY}}")
        self.assertEqual(widget["headers"], {"X-Example": "value"})
        self.assertEqual(widget["version"], 2)

    def test_management_services_share_schema_and_do_not_change_other_cards(self):
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
        self.write_routes([beszel])
        result = self.render(HOMELAB_DIRECTORY=str(homelab))
        self.assertEqual(result.returncode, 0, result.stderr)
        groups = {
            name: {key: value for card in cards for key, value in card.items()}
            for name, cards in self.groups().items()
        }
        for host, endpoint in [
            ("first", "first.lab.example.net:9090"),
            ("renamed", "renamed.lab.example.net:9443"),
        ]:
            panel = groups[f"lab-{host}"]["Example Console"]
            self.assertEqual(panel["href"], f"https://{endpoint}")
            self.assertEqual(panel["description"], "Host Administration")
            self.assertEqual(panel["icon"], "example-console")
        self.assertEqual(groups["lab-first"]["Beszel"]["icon"], "sh-beszel")
        self.assertEqual(
            groups["lab-first"]["Beszel"]["description"], "System Monitoring"
        )
        self.assertEqual(
            groups["Infrastructure"]["Netboot"]["href"],
            "http://storage.mbk.example.net:31010",
        )
        self.assertEqual(groups["mbk-storage"]["TrueNAS"]["widget"]["type"], "truenas")


if __name__ == "__main__":
    unittest.main()
