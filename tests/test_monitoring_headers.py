"""Check monitoring header Secret references resolve to 1Password references."""

import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ROUTE = {
    "cluster": "syd",
    "group": "Apps",
    "headers": {"x-gatus-token": {"name": "credentials", "key": "monitoring-token"}},
    "name": "Example",
    "namespace": "example",
    "source": "HTTPRoute/example/example",
}
RESOURCES = [
    {
        "cluster": "syd",
        "kind": "ClusterSecretStore",
        "metadata": {"name": "onepassword"},
        "spec": {"provider": {"onepassword": {"vaults": {"vault-id": 1}}}},
    },
    {
        "cluster": "syd",
        "kind": "ExternalSecret",
        "metadata": {"name": "source", "namespace": "example"},
        "spec": {
            "data": [{
                "remoteRef": {"key": "item-id", "property": "monitoring-token"},
                "secretKey": "monitoring-token",
            }],
            "secretStoreRef": {"kind": "ClusterSecretStore", "name": "onepassword"},
            "target": {"name": "credentials"},
        },
    },
]


def resolve(routes, resources):
    with tempfile.TemporaryDirectory() as directory:
        inventory = Path(directory) / "inventory.jsonl"
        secrets = Path(directory) / "secrets.jsonl"
        inventory.write_text("".join(json.dumps(route) + "\n" for route in routes))
        secrets.write_text("".join(json.dumps(resource) + "\n" for resource in resources))
        return subprocess.run(
            [
                "jq", "-s", "--slurpfile", "resources", str(secrets),
                "--from-file", "scripts/service-routes/monitoring_headers.jq", str(inventory),
            ],
            cwd=ROOT, capture_output=True, text=True,
        )


class MonitoringHeadersTests(unittest.TestCase):
    def test_headers_resolve_through_external_secret_and_store(self):
        result = resolve([ROUTE, dict(ROUTE, headers={}, name="Plain")], RESOURCES)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            [route["headers"] for route in json.loads(result.stdout)],
            [{"x-gatus-token": "op://vault-id/item-id/monitoring-token"}, {}],
        )

    def test_unsupported_declarations_fail(self):
        def changed(edit):
            resources = copy.deepcopy(RESOURCES)
            edit(resources)
            return resources

        cases = {
            "invalid monitoring header name": ([dict(ROUTE, headers={"bad header": ROUTE["headers"]["x-gatus-token"]})], RESOURCES),
            "Secret name and key": ([dict(ROUTE, headers={"x-gatus-token": {"name": "credentials"}})], RESOURCES),
            "expected one ExternalSecret": ([dict(ROUTE, namespace="other")], RESOURCES),
            "expected one 1Password vault": ([ROUTE], changed(lambda r: r[0]["spec"]["provider"]["onepassword"]["vaults"].update(other=2))),
            "direct ExternalSecret data mappings": ([ROUTE], changed(lambda r: r[1]["spec"]["target"].update(template={"data": {}}))),
            "unsupported monitoring secret mapping": ([ROUTE], changed(lambda r: r[1]["spec"]["data"][0].update(sourceRef={}))),
        }
        for message, (routes, resources) in cases.items():
            with self.subTest(message):
                result = resolve(routes, resources)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)


if __name__ == "__main__":
    unittest.main()
