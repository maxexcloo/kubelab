"""Exercise inventory refreshes for Traefik's native file provider."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from support import ROOT, read_yaml

SCRIPT = ROOT / "platform/networking/traefik/homelab/render_host_services.sh"


class HostRouteTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.data = self.directory / "homelab/data"
        self.data.mkdir(parents=True)
        (self.data / "domains.yaml").write_text(
            json.dumps({"domains": {"infrastructure": "example.net"}})
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
            "Host(`agent-browser-mercury.syd.excloo.dev`)",
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

    def test_failed_refresh_keeps_last_valid_configuration(self):
        self.assertEqual(self.render().returncode, 0)
        previous = (self.output / "homelab.yaml").read_bytes()
        (self.data / "machines.yaml").write_text("machines: [\n")
        self.assertNotEqual(self.refresh().returncode, 0)
        self.assertEqual((self.output / "homelab.yaml").read_bytes(), previous)
