"""Check Homepage dashboard providers without network access."""

import json
import os
import shutil
import unittest

from homepage_support import HOMELAB, HomepageDashboardFixture
from support import read_yaml


class HomepageProvidersTests(HomepageDashboardFixture, unittest.TestCase):
    def test_provider_widgets_discover_gatus_keys_and_dns_without_duplicate_checks(self):
        homelab = self.directory / "homelab"
        shutil.copytree(HOMELAB, homelab)
        path = homelab / "data/providers.yaml"
        providers = read_yaml(path)
        providers["providers"]["example"]["dns"] = {"name": "Example Resolver", "query-type": "A", "url": "192.0.2.53"}
        path.write_text(json.dumps(providers))
        self.gatus.write_text(json.dumps([
            {"group": "Providers", "key": "discovered_website", "name": "Example", "results": [{"success": True}]},
            {"group": "Providers", "key": "discovered_dns", "name": "Example Resolver", "results": [{"success": False}]},
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


if __name__ == "__main__":
    unittest.main()
