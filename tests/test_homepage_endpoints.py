"""Exercise Homepage's endpoint contract without fetching live inventory."""

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
SCRIPT = APP / "render_services.sh"
ENVIRONMENT = os.environ | {
    "HOMELAB_INFRASTRUCTURE_FILE": str(INFRASTRUCTURE),
    "HOMEPAGE_BESZEL_ROUTES": str(ROOT / "tests/fixtures/homepage/beszel-routes.json"),
}


def resolve(document, homelab=FIXTURE, infrastructure=INFRASTRUCTURE):
    return subprocess.run(
        ["yq", "-o=json", "--from-file", str(APP / "resolve_endpoints.yq"), "-"],
        input=json.dumps(document),
        capture_output=True,
        text=True,
        env=os.environ
        | {
            "DOMAINS": str(homelab / "data/domains.yaml"),
            "INFRASTRUCTURE": str(infrastructure),
            "MACHINES": str(homelab / "data/machines.yaml"),
        },
        check=False,
    )


def resolved(document, **arguments):
    result = resolve(document, **arguments)
    if result.returncode:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout)


def render(output, homelab=FIXTURE, **environment):
    return subprocess.run(
        ["sh", str(SCRIPT), str(output), str(homelab)],
        capture_output=True,
        env=ENVIRONMENT | environment,
        check=False,
    )


def edit_inventory(homelab, change):
    path = homelab / "data/machines.yaml"
    inventory = read_yaml(path)
    change(inventory["machines"])
    path.write_text(json.dumps(inventory))


def cards(output):
    return {
        name: entries for group in read_yaml(output) for name, entries in group.items()
    }


class HomepageEndpointsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.homelab = self.directory / "homelab"
        shutil.copytree(FIXTURE, self.homelab)
        self.output = self.directory / "services.yaml"

    def test_references_share_ports_and_preserve_paths_and_secrets(self):
        result = resolved(
            {
                "href": "homelab://mbk/kimbap/management",
                "widget": {
                    "url": "homelab://mbk/kimbap/management",
                    "key": "{{HOMEPAGE_VAR_TRUENAS_API_KEY}}",
                },
                "link": "homelab://mbk/hass/management/add-on",
                "console": "homelab://mbk/nanokvm/management",
                "local_console": "homelab://mbk/slzb-06m/management",
                "other_service": "homelab://mbk/kimbap/netboot",
            }
        )
        self.assertEqual(result["href"], "https://storage.mbk.example.net:8444")
        self.assertEqual(result["href"], result["widget"]["url"])
        self.assertEqual(result["widget"]["key"], "{{HOMEPAGE_VAR_TRUENAS_API_KEY}}")
        self.assertEqual(result["link"], "https://hass.mbk.example.net/add-on")
        self.assertEqual(
            result["other_service"], "http://storage.mbk.example.net:31010"
        )
        self.assertEqual(result["console"], "http://nanokvm.mbk.example.net")
        self.assertEqual(result["local_console"], "http://slzb-06m.mbk.example.net")

    def test_unchanged_inventory_keeps_published_files(self):
        self.assertEqual(render(self.output).returncode, 0)
        self.assertEqual(read_yaml(self.directory / "bookmarks.yaml"), [])
        timestamp = self.output.stat().st_mtime_ns
        self.assertEqual(render(self.output).returncode, 0)
        self.assertEqual(self.output.stat().st_mtime_ns, timestamp)

    def test_inventory_cards_follow_metadata_and_addresses(self):
        def change(machines):
            machine = machines["mbk"]["slzb-06m"]
            machine["hostname"] = "coordinator"
            machine["interfaces"][0]["address"] = "192.0.2.9"
            machine["services"]["diagnostics"] = dict(machine["services"]["management"])
            machine["services"]["diagnostics"].update(
                group="Infrastructure",
                name="Adapter Console",
                siteMonitor="http://192.0.2.9/status",
            )

        edit_inventory(self.homelab, change)
        result = render(self.output, self.homelab)
        self.assertEqual(result.returncode, 0, result.stderr)
        groups = cards(self.output)
        adapter = next(
            card["Adapter Console"]
            for card in groups["Infrastructure"]
            if "Adapter Console" in card
        )
        self.assertEqual(adapter["href"], "http://coordinator.mbk.example.net")
        self.assertEqual(adapter["siteMonitor"], "http://192.0.2.9/status")
        self.assertFalse(
            any("Adapter Console" in card for card in groups["mbk-coordinator"])
        )
        self.assertEqual(adapter["icon"], "zigbee")
        self.assertEqual(
            adapter["description"], "Zigbee Ethernet Adapter • mbk-coordinator"
        )
        self.assertEqual(
            groups["mbk-nanokvm"][0]["NanoKVM"]["href"],
            "http://nanokvm.mbk.example.net",
        )
        self.assertEqual(
            groups["mbk-nanokvm"][0]["NanoKVM"]["siteMonitor"],
            "http://nanokvm.mbk.example.net",
        )

    def test_grouped_services_and_providers_become_home_cards_with_widgets(self):
        def change(machines):
            management = machines["mbk"]["kimbap"]["services"]["management"]
            management.update(
                group="Infrastructure",
                name="TrueNAS",
                widget={"key": "{{HOMEPAGE_VAR_TRUENAS_API_KEY}}", "type": "truenas"},
            )
            machines["mbk"]["slzb-06m"]["services"]["management"]["group"] = (
                "Smart Home"
            )

        edit_inventory(self.homelab, change)
        result = render(self.output, self.homelab)
        self.assertEqual(result.returncode, 0, result.stderr)
        groups = cards(self.output)
        truenas = next(
            card["TrueNAS"] for card in groups["Infrastructure"] if "TrueNAS" in card
        )
        self.assertEqual(
            truenas["widget"],
            {
                "key": "{{HOMEPAGE_VAR_TRUENAS_API_KEY}}",
                "type": "truenas",
                "url": "https://storage.mbk.example.net:8444",
            },
        )
        self.assertTrue(any("TrueNAS" in card for card in groups["mbk-storage"]))
        home = [card for card in groups["Smart Home"] if "SLZB-06M" in card]
        servers = [card for card in groups["mbk-slzb-06m"] if "SLZB-06M" in card]
        self.assertEqual(len(home), 1)
        self.assertEqual(len(servers), 1)
        self.assertEqual(home[0]["SLZB-06M"]["href"], servers[0]["SLZB-06M"]["href"])
        gatus = next(card["Gatus"] for card in groups["Operations"] if "Gatus" in card)
        self.assertEqual(gatus["href"], "https://status.example.net")
        self.assertEqual(
            gatus["widget"], {"type": "gatus", "url": "https://status.example.net"}
        )
        self.assertNotIn(
            "Example",
            {name for group in groups.values() for card in group for name in card},
        )

    def test_published_hosts_apply_only_to_http(self):
        published = self.directory / "infrastructure.json"
        for host in [
            "published.example.net",
            "100.64.0.9",
            "storage.internal",
            "192.0.2.9",
            None,
        ]:
            with self.subTest(host=host):
                published.write_text(json.dumps({"hosts": {"kimbap": host}}))
                result = resolved(
                    {
                        "http": "homelab://mbk/kimbap/netboot",
                        "https": "homelab://mbk/kimbap/management/path",
                    },
                    infrastructure=published,
                )
                self.assertEqual(
                    result["http"], f"http://{host or 'storage.mbk.example.net'}:31010"
                )
                self.assertEqual(
                    result["https"], "https://storage.mbk.example.net:8444/path"
                )

    def test_service_hostname_overrides_machine_and_published_addresses(self):
        published = self.directory / "infrastructure.json"
        published.write_text(json.dumps({"hosts": {"kimbap": "100.64.0.9"}}))
        for scheme, port in [("http", 80), ("https", 443), ("https", 8443)]:
            with self.subTest(scheme=scheme, port=port):
                edit_inventory(
                    self.homelab,
                    lambda machines, port=port, scheme=scheme: machines["mbk"][
                        "kimbap"
                    ]["services"]["management"].update(
                        hostname="studio.example.com", port=port, scheme=scheme
                    ),
                )
                result = resolved(
                    {"href": "homelab://mbk/kimbap/management/path"},
                    homelab=self.homelab,
                    infrastructure=published,
                )
                authority = "studio.example.com" + (":8443" if port == 8443 else "")
                self.assertEqual(result["href"], f"{scheme}://{authority}/path")
        edit_inventory(
            self.homelab,
            lambda machines: machines["mbk"]["kimbap"]["services"]["management"].update(
                dns_lan=True
            ),
        )
        self.assertEqual(
            resolved({"href": "homelab://mbk/kimbap/management"}, homelab=self.homelab)[
                "href"
            ],
            "https://storage.mbk.example.net:8443",
        )
        edit_inventory(
            self.homelab,
            lambda machines: machines["mbk"]["kimbap"]["services"]["management"].update(
                hostname="https://invalid.example/path"
            ),
        )
        self.assertNotEqual(
            resolve(
                {"href": "homelab://mbk/kimbap/management"}, homelab=self.homelab
            ).returncode,
            0,
        )

    def test_service_paths_share_a_hostname_without_losing_the_prefix(self):
        document = {
            "root": "homelab://mbk/kimbap/management",
            "child": "homelab://mbk/kimbap/management/api/config",
        }
        for path in ["/files/", "/radiance/", "/files"]:
            with self.subTest(path=path):
                edit_inventory(
                    self.homelab,
                    lambda machines, path=path: machines["mbk"]["kimbap"]["services"][
                        "management"
                    ].update(
                        hostname="ai.example.com", path=path, port=443, scheme="https"
                    ),
                )
                result = resolved(document, homelab=self.homelab)
                self.assertEqual(result["root"], "https://ai.example.com" + path)
                self.assertEqual(
                    result["child"],
                    "https://ai.example.com" + path.rstrip("/") + "/api/config",
                )
        edit_inventory(
            self.homelab,
            lambda machines: machines["mbk"]["kimbap"]["services"]["management"].update(
                path="https://invalid.example/path"
            ),
        )
        self.assertNotEqual(resolve(document, homelab=self.homelab).returncode, 0)

    def test_invalid_endpoint_settings_preserve_previous_configuration(self):
        self.output.write_text("previous configuration\n")
        for scheme, port in [
            ("ftp", 443),
            ("https", 0),
            ("https", 65536),
            ("https", "invalid"),
            ("https", 443.5),
        ]:
            with self.subTest(scheme=scheme, port=port):
                edit_inventory(
                    self.homelab,
                    lambda machines, port=port, scheme=scheme: machines["mbk"][
                        "kimbap"
                    ]["services"]["management"].update(port=port, scheme=scheme),
                )
                self.assertNotEqual(render(self.output, self.homelab).returncode, 0)
                self.assertEqual(self.output.read_text(), "previous configuration\n")

    def test_invalid_yaml_preserves_previous_configuration(self):
        (self.homelab / "data/machines.yaml").write_text("machines: [broken YAML\n")
        self.output.write_text("previous configuration\n")
        self.assertNotEqual(render(self.output, self.homelab).returncode, 0)
        self.assertEqual(self.output.read_text(), "previous configuration\n")

    def test_invalid_references_fail(self):
        for reference in [
            "homelab://mbk/missing/management",
            "homelab://mbk/kimbap/missing",
        ]:
            with self.subTest(reference=reference):
                result = resolve({"href": reference})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Missing or invalid endpoint reference", result.stderr)


if __name__ == "__main__":
    unittest.main()
