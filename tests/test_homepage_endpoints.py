"""Exercise Homepage's endpoint contract without fetching live inventory."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests/fixtures/homepage/homelab"
SCRIPT = ROOT / "apps/base/homepage/render_services.sh"


class HomepageEndpointsTests(unittest.TestCase):
    def test_references_share_ports_and_preserve_paths_and_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            template = Path(directory) / "source.yaml"
            output = Path(directory) / "services.yaml"
            template.write_text(json.dumps({
                "href": "homelab://mbk/kimbap/management",
                "siteMonitor": "homelab://mbk/kimbap/management",
                "widget": {
                    "url": "homelab://mbk/kimbap/management",
                    "key": "{{HOMEPAGE_FILE_TRUENAS_KEY}}",
                },
                "link": "homelab://mbk/hass/management/add-on",
                "fly": "homelab-dns://excloo-gatus.fly.dev",
                "console": "homelab://mbk/nanokvm/console",
                "local_console": "homelab://mbk/slzb-06m/console",
                "other_service": "homelab://mbk/kimbap/netboot",
            }))
            subprocess.run(["sh", str(SCRIPT), str(template), str(output), str(FIXTURE)], check=True)
            result = json.loads(subprocess.check_output(["yq", "-o=json", ".", str(output)]))
            self.assertEqual(result["href"], "https://storage.mbk.example.net:8444")
            self.assertEqual(result["href"], result["siteMonitor"])
            self.assertEqual(result["href"], result["widget"]["url"])
            self.assertEqual(result["widget"]["key"], "{{HOMEPAGE_FILE_TRUENAS_KEY}}")
            self.assertEqual(result["link"], "https://hass.mbk.example.net/add-on")
            self.assertEqual(result["other_service"], "http://storage.mbk.example.net:31010")
            self.assertEqual(result["fly"], "https://status.example.net")
            self.assertEqual(result["console"], "http://nanokvm.mbk.example.net")
            self.assertEqual(result["local_console"], "http://slzb-06m.mbk.example.net")
            bookmarks = json.loads(subprocess.check_output([
                "yq", "-o=json", ".", str(Path(directory) / "bookmarks.yaml")
            ]))
            self.assertEqual(bookmarks, [{"Providers": [{"Example": [{
                "description": "Example provider", "href": "https://provider.example.com", "icon": "example"
            }]}]}])
            timestamp = output.stat().st_mtime_ns
            subprocess.run(["sh", str(SCRIPT), str(template), str(output), str(FIXTURE)], check=True)
            self.assertEqual(output.stat().st_mtime_ns, timestamp)

    def test_inventory_cards_follow_metadata_and_addresses(self):
        with tempfile.TemporaryDirectory() as directory:
            homelab = Path(directory) / "homelab"
            shutil.copytree(FIXTURE, homelab)
            inventory_path = homelab / "data/machines.yaml"
            inventory = json.loads(subprocess.check_output(["yq", "-o=json", ".", str(inventory_path)]))
            machine = inventory["machines"]["mbk"]["slzb-06m"]
            machine["hostname"] = "coordinator"
            machine["interfaces"][0]["address"] = "192.0.2.9"
            machine["services"]["console"]["homepage"]["name"] = "Adapter Console"
            inventory_path.write_text(json.dumps(inventory))
            template = Path(directory) / "source.yaml"
            template.write_text("[]\n")
            output = Path(directory) / "services.yaml"
            subprocess.run(["sh", str(SCRIPT), str(template), str(output), str(homelab)], check=True)
            groups = json.loads(subprocess.check_output(["yq", "-o=json", ".", str(output)]))
            cards = {name: entries for group in groups for name, entries in group.items()}
            adapter = cards["mbk-coordinator"][0]["Adapter Console"]
            self.assertEqual(adapter["href"], "http://coordinator.mbk.example.net")
            self.assertEqual(adapter["icon"], "zigbee")
            self.assertEqual(adapter["description"], "Zigbee Ethernet Adapter")
            self.assertEqual(cards["mbk-nanokvm"][0]["NanoKVM"]["href"], "http://nanokvm.mbk.example.net")

    def test_published_hosts_apply_only_to_http(self):
        with tempfile.TemporaryDirectory() as directory:
            template = Path(directory) / "source.yaml"
            output = Path(directory) / "services.yaml"
            published = Path(directory) / "infrastructure.json"
            template.write_text(json.dumps({
                "http": "homelab://mbk/kimbap/netboot",
                "https": "homelab://mbk/kimbap/management/path",
            }))
            for host in ["published.example.net", "100.64.0.9", "storage.internal", "192.0.2.9", None]:
                with self.subTest(host=host):
                    published.write_text(json.dumps({"hosts": {"kimbap": host}}))
                    subprocess.run(["sh", str(SCRIPT), str(template), str(output), str(FIXTURE)],
                                   check=True, env=os.environ | {"HOMELAB_INFRASTRUCTURE_FILE": str(published)})
                    result = json.loads(subprocess.check_output(["yq", "-o=json", ".", str(output)]))
                    self.assertEqual(result["http"], f"http://{host or 'storage.mbk.example.net'}:31010")
                    self.assertEqual(result["https"], "https://storage.mbk.example.net:8444/path")

    def test_invalid_yaml_preserves_previous_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            template = Path(directory) / "source.yaml"
            output = Path(directory) / "services.yaml"
            template.write_text("services: [broken YAML\n")
            output.write_text("previous configuration\n")
            result = subprocess.run(
                ["sh", str(SCRIPT), str(template), str(output), str(FIXTURE)],
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(output.read_text(), "previous configuration\n")

    def test_invalid_references_preserve_previous_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            template = Path(directory) / "source.yaml"
            output = Path(directory) / "services.yaml"
            output.write_text("previous configuration\n")
            for reference in ["homelab://mbk/missing/management", "homelab://mbk/kimbap/missing",
                              "homelab-dns://missing.fly.dev"]:
                with self.subTest(reference=reference):
                    template.write_text(json.dumps({"href": reference}))
                    result = subprocess.run(
                        ["sh", str(SCRIPT), str(template), str(output), str(FIXTURE)],
                        capture_output=True,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(output.read_text(), "previous configuration\n")


if __name__ == "__main__":
    unittest.main()
