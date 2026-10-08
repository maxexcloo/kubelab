"""Exercise Homepage's endpoint contract without fetching live inventory."""

import json
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
                    "key": "{{HOMEPAGE_VAR_TRUENAS_KEY}}",
                },
                "link": "homelab://mbk/hass/management/add-on",
                "other_service": "homelab://mbk/kimbap/netboot",
            }))
            subprocess.run(["sh", str(SCRIPT), str(template), str(output), str(FIXTURE)], check=True)
            result = json.loads(subprocess.check_output(["yq", "-o=json", ".", str(output)]))
            self.assertEqual(result["href"], "https://storage.mbk.example.net:8444")
            self.assertEqual(result["href"], result["siteMonitor"])
            self.assertEqual(result["href"], result["widget"]["url"])
            self.assertEqual(result["widget"]["key"], "{{HOMEPAGE_VAR_TRUENAS_KEY}}")
            self.assertEqual(result["link"], "https://hass.mbk.example.net/add-on")
            self.assertEqual(result["other_service"], "http://storage.mbk.example.net:31010")
            bookmarks = json.loads(subprocess.check_output([
                "yq", "-o=json", ".", str(Path(directory) / "bookmarks.yaml")
            ]))
            self.assertEqual(bookmarks, [{"Providers": [{"Example": [{
                "description": "Example provider", "href": "https://provider.example.com", "icon": "example"
            }]}]}])
            timestamp = output.stat().st_mtime_ns
            subprocess.run(["sh", str(SCRIPT), str(template), str(output), str(FIXTURE)], check=True)
            self.assertEqual(output.stat().st_mtime_ns, timestamp)

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
            for reference in ["homelab://mbk/missing/management", "homelab://mbk/kimbap/missing"]:
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
