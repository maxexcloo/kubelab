"""Check Homepage dashboard sources without network access."""

import json
import shutil
import unittest

from homepage_support import HOMELAB, HomepageDashboardFixture, route
from support import read_yaml


class HomepageSourcesTests(HomepageDashboardFixture, unittest.TestCase):
    def test_live_routes_include_minilab_apps(self):
        feeds = route(
            "Minilab: Feeds", group="Minilab", href="https://feeds.mini.example.net"
        )
        feeds["metadata"].update({"name": "feeds", "namespace": "feeds"})
        self.write_routes([route("Existing"), feeds])
        result = self.render()
        self.assertEqual(result.returncode, 0, result.stderr)
        services = self.services()
        self.assertIn("Existing", services)
        self.assertEqual(services["Feeds"]["href"], "https://feeds.mini.example.net")
        groups = self.groups()
        self.assertEqual([next(iter(card)) for card in groups["Mini"]], ["Feeds"])
        # Only the Home group states the source; cluster groups keep the prefix.
        self.assertIn(
            "Minilab: Feeds",
            [next(iter(card)) for card in self.groups("Clusters")["mbk/node"]],
        )
        # Removed apps disappear without maintaining a second list of cards.
        self.write_routes([route("New Tool")])
        self.assertEqual(self.render().returncode, 0)
        self.assertIn("New Tool", self.services())
        self.assertNotIn("Feeds", self.services())

    def test_required_inputs_fail_without_publishing(self):
        for name in ("HOMELAB_INFRASTRUCTURE_FILE", "KUBECTL"):
            with self.subTest(name=name):
                result = self.render(**{name: ""})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f"{name} is required", result.stderr)
                self.assertFalse(self.output.exists())

    def test_unchanged_refresh_and_invalid_input_preserve_files(self):
        result = self.render()
        self.assertEqual(result.returncode, 0, result.stderr)

        def files():
            return {
                p.name: (p.read_bytes(), p.stat().st_mtime_ns)
                for p in self.output.iterdir()
            }

        before = files()
        self.assertEqual(self.render().returncode, 0)
        self.assertEqual(before, files())
        valid_routes = self.routes.read_text()
        for routes in ("[broken json", '{"items": []}'):
            self.routes.write_text(routes)
            self.assertNotEqual(self.render().returncode, 0)
            self.assertEqual(before, files())
        self.routes.write_text(valid_routes)
        homelab = self.directory / "homelab"
        shutil.copytree(HOMELAB, homelab)
        machines = homelab / "data/machines.yaml"
        inventory = read_yaml(machines)
        inventory["machines"]["mbk"]["saturn"]["services"]["management"]["scheme"] = (
            "ftp"
        )
        machines.write_text(json.dumps(inventory))
        self.assertNotEqual(self.render(HOMELAB_DIRECTORY=str(homelab)).returncode, 0)
        self.assertEqual(before, files())


if __name__ == "__main__":
    unittest.main()
