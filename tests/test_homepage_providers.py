"""Check Homepage dashboard providers without network access."""

import json
import shutil
import unittest

from homepage_support import HOMELAB, HomepageDashboardFixture
from support import read_yaml


class HomepageProvidersTests(HomepageDashboardFixture, unittest.TestCase):
    def test_provider_widgets_follow_gatus_endpoint_keys(self):
        homelab = self.directory / "homelab"
        shutil.copytree(HOMELAB, homelab)
        path = homelab / "data/providers.yaml"
        providers = read_yaml(path)
        providers["providers"]["example"]["dns"] = {
            "query-type": "A",
            "url": "192.0.2.53",
        }
        providers["providers"]["gatus"]["monitoring"] = False
        path.write_text(json.dumps(providers))
        result = self.render(HOMELAB_DIRECTORY=str(homelab))
        self.assertEqual(result.returncode, 0, result.stderr)
        cards = {
            name: value
            for card in self.groups("Providers")["Providers"]
            for name, value in card.items()
        }
        self.assertEqual(set(cards), {"Example", "Example DNS"})
        self.assertEqual(cards["Example DNS"]["description"], "DNS Resolver")
        self.assertEqual(cards["Example"]["description"], "Example provider")
        for name, key in [
            ("Example", "providers_example"),
            ("Example DNS", "providers_example-dns"),
        ]:
            card = cards[name]
            self.assertEqual(card["icon"], "example")
            self.assertEqual(card["href"], "https://provider.example.com")
            self.assertNotIn("siteMonitor", card)
            self.assertEqual(card["widget"]["type"], "customapi")
            self.assertEqual(
                card["widget"]["url"],
                f"https://status.example.net/api/v1/endpoints/{key}/statuses?page=1&pageSize=1",
            )
            # Whole milliseconds: the number format truncates after scaling.
            self.assertEqual(card["widget"]["mappings"][1]["format"], "number")
        self.assertEqual(read_yaml(self.output / "bookmarks.yaml"), [])
        layout = read_yaml(self.output / "settings.yaml")["layout"]
        self.assertEqual(list(layout), ["Home", "Clusters", "Providers", "Servers"])
        self.assertEqual(layout["Providers"]["tab"], "Providers")


if __name__ == "__main__":
    unittest.main()
