"""Exercise Homepage's published endpoint contract without live inventory."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from support import ROOT, read_yaml

APP = ROOT / "apps/base/homepage"
FIXTURE = ROOT / "tests/fixtures/homepage/homelab"
INFRASTRUCTURE = ROOT / "tests/fixtures/homepage/infrastructure.json"


def resolve(document, homelab=FIXTURE, infrastructure=INFRASTRUCTURE):
    return subprocess.run(
        ["yq", "-o=json", "--from-file", str(APP / "resolve_endpoints.yq"), "-"],
        input=json.dumps(document),
        capture_output=True,
        text=True,
        env=os.environ
        | {
            "INVENTORY": str(homelab / "inventory.json"),
            "INFRASTRUCTURE": str(infrastructure),
        },
        check=False,
    )


class HomepageEndpointsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.homelab = self.directory / "homelab"
        shutil.copytree(FIXTURE, self.homelab)

    def resolved(self, document, **arguments):
        result = resolve(document, **arguments)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_references_use_published_urls_and_preserve_paths_and_secrets(self):
        result = self.resolved(
            {
                "href": "homelab://mbk/saturn/management",
                "widget": {
                    "url": "homelab://mbk/saturn/management",
                    "key": "{{HOMEPAGE_VAR_TRUENAS_API_KEY}}",
                },
                "link": "homelab://mbk/luna/esphome/add-on",
                "console": "homelab://mbk/nanokvm/management",
            }
        )
        self.assertEqual(result["href"], "https://storage.mbk.example.net:8444")
        self.assertEqual(result["href"], result["widget"]["url"])
        self.assertEqual(result["widget"]["key"], "{{HOMEPAGE_VAR_TRUENAS_API_KEY}}")
        self.assertEqual(
            result["link"], "https://luna.mbk.example.net/5c53de3b_esphome/add-on"
        )
        self.assertEqual(result["console"], "http://nanokvm.mbk.example.net")

    def test_published_hosts_apply_only_to_http_without_service_hostnames(self):
        published = self.directory / "infrastructure.json"
        published.write_text(json.dumps({"hosts": {"saturn": "100.64.0.9"}}))
        result = self.resolved(
            {
                "http": "homelab://mbk/saturn/netboot",
                "https": "homelab://mbk/saturn/management/path",
            },
            infrastructure=published,
        )
        self.assertEqual(result["http"], "http://100.64.0.9:31010")
        self.assertEqual(result["https"], "https://storage.mbk.example.net:8444/path")
        path = self.homelab / "inventory.json"
        inventory = read_yaml(path)
        inventory["services"]["saturn/netboot"].update(
            hostname="studio.example.com", url="http://studio.example.com/files/"
        )
        path.write_text(json.dumps(inventory))
        result = self.resolved(
            {"href": "homelab://mbk/saturn/netboot/api"},
            homelab=self.homelab,
            infrastructure=published,
        )
        self.assertEqual(result["href"], "http://studio.example.com/files/api")

    def test_lan_service_hostnames_keep_certificate_dns(self):
        path = self.homelab / "inventory.json"
        inventory = read_yaml(path)
        inventory["services"]["saturn/management"].update(
            dns_lan=True,
            hostname="panel.internal",
            url="https://panel.internal:8444/files",
        )
        path.write_text(json.dumps(inventory))
        self.assertEqual(
            self.resolved(
                {"href": "homelab://mbk/saturn/management/api"}, homelab=self.homelab
            )["href"],
            "https://storage.mbk.example.net:8444/files/api",
        )

    def test_invalid_references_fail(self):
        for reference in [
            "homelab://mbk/missing/management",
            "homelab://mbk/saturn/missing",
            "homelab://wrong/saturn/management",
        ]:
            with self.subTest(reference=reference):
                result = resolve({"href": reference})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Missing or invalid endpoint reference", result.stderr)


if __name__ == "__main__":
    unittest.main()
