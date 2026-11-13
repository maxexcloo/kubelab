"""Exercise inventory refreshes for Traefik's native file provider."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from support import ROOT, read_resources, read_yaml, repository_resources

SCRIPT = ROOT / "platform/networking/traefik/homelab/render_host_services.sh"


class HostRouteTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.data = self.directory / "homelab/data"
        self.data.mkdir(parents=True)
        (self.data / "domains.yaml").write_text(
            json.dumps(
                {
                    "domains": {
                        "infrastructure": "example.net",
                        "services": "example.dev",
                    }
                }
            )
        )
        self.services = {
            "agent-browser": {"private_proxy": "syd", "scheme": "http", "port": 9222},
            "other-cluster": {
                "private_proxy": "elsewhere",
                "scheme": "http",
                "port": 80,
            },
            "unselected": {"scheme": "http", "port": 80},
        }
        self.output = self.directory / "output"

    def render(self):
        (self.data / "machines.yaml").write_text(
            json.dumps({"machines": {"mbk": {"mercury": {"services": self.services}}}})
        )
        return self.refresh()

    def refresh(self):
        return subprocess.run(
            ["sh", str(SCRIPT), str(self.output)],
            capture_output=True,
            text=True,
            env=os.environ
            | {"HOMELAB_CLUSTER": "syd", "HOMELAB_DIRECTORY": str(self.data.parent)},
            check=False,
        )

    def configuration(self):
        return read_yaml(self.output / "homelab.yaml")["http"]

    def test_selected_services_use_private_https_and_owner_upstreams(self):
        self.services["syncthing"] = {
            "private_proxy": "syd",
            "scheme": "https",
            "hostname": "gui.mercury.example.net",
            "port": 8384,
        }
        result = self.render()
        self.assertEqual(result.returncode, 0, result.stderr)
        config = self.configuration()
        self.assertEqual(
            set(config["routers"]), {"agent-browser-mercury", "syncthing-mercury"}
        )
        router = config["routers"]["agent-browser-mercury"]
        self.assertEqual(router["entryPoints"], ["websecure"])
        self.assertEqual(router["tls"], {})
        self.assertEqual(
            router["rule"],
            "Host(`agent-browser.mercury.example.net`) || "
            "Host(`agent-browser-mercury.syd.example.dev`)",
        )
        self.assertEqual(
            config["services"][router["service"]],
            {
                "loadBalancer": {
                    "servers": [{"url": "http://mercury.mbk.example.net:9222"}]
                }
            },
        )
        self.assertEqual(
            config["services"]["syncthing-mercury"],
            {
                "loadBalancer": {
                    "servers": [{"url": "https://gui.mercury.example.net:8384"}]
                }
            },
        )

    def test_refresh_tracks_inventory_additions_changes_and_removals(self):
        self.assertEqual(self.render().returncode, 0)
        self.services["syncthing"] = {
            "private_proxy": "syd",
            "scheme": "http",
            "port": 8384,
        }
        del self.services["agent-browser"]["private_proxy"]
        self.assertEqual(self.render().returncode, 0)
        config = self.configuration()
        self.assertEqual(set(config["routers"]), {"syncthing-mercury"})
        self.assertEqual(set(config["services"]), {"syncthing-mercury"})
        self.services["syncthing"]["port"] = 8385
        self.assertEqual(self.render().returncode, 0)
        self.assertEqual(
            self.configuration()["services"]["syncthing-mercury"]["loadBalancer"][
                "servers"
            ],
            [{"url": "http://mercury.mbk.example.net:8385"}],
        )

    def test_removing_all_opt_ins_clears_routes(self):
        self.assertEqual(self.render().returncode, 0)
        del self.services["agent-browser"]["private_proxy"]
        self.assertEqual(self.render().returncode, 0)
        self.assertEqual(self.configuration(), {"routers": {}, "services": {}})

    def test_certificate_follows_the_required_owner_input(self):
        resources = repository_resources("clusters/syd")
        reconciliation = next(
            item
            for item in resources
            if item["kind"] == "Kustomization"
            and item["metadata"]["name"] == "homelab-services"
        )
        settings = next(
            item
            for item in repository_resources("clusters/syd/platform")
            if item["kind"] == "ExternalSecret"
            and item["metadata"]["name"] == "homelab-services-settings"
        )
        reference = reconciliation["spec"]["postBuild"]["substituteFrom"][0]
        self.assertEqual(reference["name"], settings["spec"]["target"]["name"])
        self.assertFalse(reference.get("optional", False))
        owner_input = settings["spec"]["data"][0]
        self.assertEqual(
            owner_input["remoteRef"],
            {"key": "Infrastructure Inventory", "property": "private-proxy-dns-names"},
        )
        for names in (
            ["private.example.net"],
            ["private.example.net", "new.fixture.example.net"],
        ):
            with self.subTest(names=names):
                reconciliation["spec"]["postBuild"]["substitute"] = {
                    owner_input["secretKey"]: json.dumps(names)
                }
                configuration = self.directory / "flux.yaml"
                configuration.write_text(json.dumps(reconciliation))
                rendered = self.directory / "certificates.yaml"
                with rendered.open("w") as output:
                    subprocess.run(
                        [
                            "flux",
                            "build",
                            "kustomization",
                            "homelab-services",
                            "--dry-run",
                            "--strict-substitute",
                            "--in-memory-build",
                            "--path",
                            str(ROOT / reconciliation["spec"]["path"]),
                            "--kustomization-file",
                            str(configuration),
                        ],
                        stdout=output,
                        check=True,
                    )
                certificates = read_resources(rendered)
                certificate = next(
                    item for item in certificates if item["kind"] == "Certificate"
                )
                store = next(
                    item for item in certificates if item["kind"] == "TLSStore"
                )
                self.assertEqual(certificate["spec"]["dnsNames"], names)
                self.assertEqual(
                    store["spec"]["defaultCertificate"]["secretName"],
                    certificate["spec"]["secretName"],
                )

    def test_offline_certificate_inputs_do_not_become_monitoring_targets(self):
        inventory = json.loads(
            subprocess.check_output(
                ["bash", "scripts/render_service_inventory.sh"], cwd=ROOT, text=True
            )
        )
        certificate_hosts = {
            item["hostname"] for item in inventory if item["type"] == "certificate"
        }
        fixture = read_yaml(ROOT / "tests/fixtures/flux/homelab-services-settings.yaml")
        fixture_hosts = json.loads(fixture["homelab_private_proxy_dns_names"])
        self.assertTrue(certificate_hosts)
        self.assertTrue(certificate_hosts.isdisjoint(fixture_hosts))

    def test_failed_refresh_keeps_last_valid_configuration(self):
        self.assertEqual(self.render().returncode, 0)
        previous = (self.output / "homelab.yaml").read_bytes()
        (self.data / "machines.yaml").write_text("machines: [\n")
        self.assertNotEqual(self.refresh().returncode, 0)
        self.assertEqual((self.output / "homelab.yaml").read_bytes(), previous)
