"""Check DNS publishing validation against rendered manifests."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from support import read_resources

ROOT = Path(__file__).resolve().parent.parent


class ServiceInventoryTests(unittest.TestCase):
    def test_dns_publishing_follows_public_and_private_route_transitions(self):
        with tempfile.TemporaryDirectory() as directory:
            manifests = Path(directory)
            subprocess.run(
                ["scripts/render_manifests.sh", str(manifests)],
                cwd=ROOT,
                check=True,
            )
            source = manifests / "apps/overlays/syd.yaml"
            resources = read_resources(source)
            release = next(
                resource
                for resource in resources
                if resource["kind"] == "HelmRelease"
                and resource["metadata"]["name"] == "reactive-resume"
            )
            dns = next(
                resource
                for resource in resources
                if resource["kind"] == "PrivateDNSRecord"
                and resource["metadata"]["namespace"] == "reactive-resume"
            )
            routes = release["spec"]["values"]["route"]
            composition = dns["spec"]["crossplane"]["compositionRef"]

            def check():
                source.write_text(
                    "\n---\n".join(json.dumps(resource) for resource in resources)
                )
                return subprocess.run(
                    ["scripts/check_service_metadata.sh", str(manifests)],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    check=False,
                )

            result = check()
            self.assertEqual(result.returncode, 0, result.stderr)
            public = routes.pop("public")
            routes["private"]["annotations"] = public["annotations"]
            result = check()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "use private-dns to publish a private hostname in Cloudflare",
                result.stderr,
            )
            composition["name"] = "private-dns-record"
            result = check()
            self.assertEqual(result.returncode, 0, result.stderr)
            del routes["private"]["annotations"]
            routes["public"] = public
            result = check()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "use private-dns-control-d-only for a public hostname", result.stderr
            )
            composition["name"] = "private-dns-record-control-d-only"
            result = check()
            self.assertEqual(result.returncode, 0, result.stderr)
