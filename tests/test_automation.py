"""Exercise API comparisons with responses, independently of live services."""

import copy
import json
import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def composition_resource(path, name, *, base=True):
    result = subprocess.run(
        [
            "yq",
            "-o=json",
            'select(.kind == "Composition") | .spec.pipeline[0].input.resources[] '
            f'| select(.name == "{name}")' + (" | .base" if base else ""),
            ROOT / path,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def evaluate(expression, data):
    result = subprocess.run(
        ["jq", "-c", expression],
        input=json.dumps(data),
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


class PrivateDNSComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        resource = composition_resource(
            "platform/automation/private-dns/composition/composition.yaml", "control-d-rule"
        )
        # The provider resolves placeholders in the expression, not in payload.
        cls.expression = resource["spec"]["forProvider"]["expectedResponseCheck"]["logic"]
        cls.expression = cls.expression.replace(
            "{{ private-dns-target-ipv4:crossplane-system:address }}", "100.64.0.1"
        ).replace("{{ private-dns-target-ipv6:crossplane-system:address }}", "fd00::1")

    def setUp(self):
        self.data = {
            "payload": {
                "body": {
                    "hostname": "reader.example.com",
                    "ipv6Enabled": True,
                    "ipv4": "{{ private-dns-target-ipv4:crossplane-system:address }}",
                    "ipv6": "{{ private-dns-target-ipv6:crossplane-system:address }}",
                },
            },
            "response": {
                "statusCode": 200,
                "body": {
                    "body": {
                        "rules": [
                            {
                                "PK": "reader.example.com",
                                "action": {
                                    "do": 2,
                                    "status": 1,
                                    "via": "100.64.0.1",
                                    "via_v6": "fd00::1",
                                },
                            },
                        ],
                    },
                },
            },
        }

    def test_matching_rule_is_in_sync(self):
        self.assertTrue(evaluate(self.expression, self.data))

    def test_changed_rule_is_out_of_sync(self):
        for key, value in {"do": 0, "status": 0, "via": "100.64.0.2", "via_v6": "fd00::2"}.items():
            with self.subTest(key=key):
                data = copy.deepcopy(self.data)
                data["response"]["body"]["body"]["rules"][0]["action"][key] = value
                self.assertFalse(evaluate(self.expression, data))

    def test_missing_duplicate_and_unrelated_rules_are_out_of_sync(self):
        rules = self.data["response"]["body"]["body"]["rules"]
        for replacement in [[], rules * 2, [dict(rules[0], PK="another.example.com")]]:
            with self.subTest(rules=replacement):
                data = copy.deepcopy(self.data)
                data["response"]["body"]["body"]["rules"] = replacement
                self.assertFalse(evaluate(self.expression, data))

    def test_ipv4_only_rule_requires_blocked_ipv6_target(self):
        self.data["payload"]["body"]["ipv6Enabled"] = False
        action = self.data["response"]["body"]["body"]["rules"][0]["action"]
        self.assertFalse(evaluate(self.expression, self.data))
        for incorrect in [None, "", "2606:4700::1"]:
            action["via_v6"] = incorrect
            self.assertFalse(evaluate(self.expression, self.data))
        action["via_v6"] = "::"
        self.assertTrue(evaluate(self.expression, self.data))
        action["via"] = "100.64.0.2"
        self.assertFalse(evaluate(self.expression, self.data))

    def test_ipv4_only_update_blocks_public_ipv6_fallback(self):
        resource = composition_resource(
            "platform/automation/private-dns/composition/composition.yaml", "control-d-rule"
        )
        expression = next(
            mapping["body"] for mapping in resource["spec"]["forProvider"]["mappings"]
            if mapping["action"] == "UPDATE"
        )
        self.data["payload"]["body"]["ipv6Enabled"] = False
        result = evaluate(expression, self.data)
        self.assertEqual(result["via_v6"], "::")
        self.assertEqual(result["via"], self.data["payload"]["body"]["ipv4"])
        self.data["payload"]["body"]["ipv6Enabled"] = True
        self.assertEqual(evaluate(expression, self.data)["via_v6"], self.data["payload"]["body"]["ipv6"])

    def test_missing_rule_is_created_only_after_successful_listing(self):
        resource = composition_resource(
            "platform/automation/private-dns/composition/composition.yaml", "control-d-rule"
        )
        expression = resource["spec"]["forProvider"]["isRemovedCheck"]["logic"]
        self.data["response"]["body"]["success"] = True
        self.assertFalse(evaluate(expression, self.data))
        self.data["response"]["body"]["body"]["rules"] = []
        self.assertTrue(evaluate(expression, self.data))
        for response in [
            {"statusCode": 403, "body": {"success": False}},
            {"statusCode": 200, "body": {"success": False, "body": {"rules": []}}},
            {"statusCode": 200, "body": {"success": True, "body": {}}},
        ]:
            self.data["response"] = response
            self.assertFalse(evaluate(expression, self.data))

    def test_create_and_update_use_matching_bodies_and_distinct_methods(self):
        resource = composition_resource(
            "platform/automation/private-dns/composition/composition.yaml", "control-d-rule"
        )
        mappings = {m["action"]: m for m in resource["spec"]["forProvider"]["mappings"]}
        self.assertEqual(mappings["CREATE"]["method"], "POST")
        self.assertEqual(mappings["UPDATE"]["method"], "PUT")
        for enabled in [False, True]:
            self.data["payload"]["body"]["ipv6Enabled"] = enabled
            created = evaluate(mappings["CREATE"]["body"], self.data)
            updated = evaluate(mappings["UPDATE"]["body"], self.data)
            self.assertEqual(created, updated)
            self.assertEqual(created["via_v6"], self.data["payload"]["body"]["ipv6"] if enabled else "::")
            self.assertEqual(created["hostnames"], ["reader.example.com"])

    def test_api_error_is_out_of_sync(self):
        self.data["response"] = {"statusCode": 403, "body": {"error": "forbidden"}}
        self.assertFalse(evaluate(self.expression, self.data))


class PrivateDNSCompositionTests(unittest.TestCase):
    def test_control_d_only_preserves_rule_without_public_dns_resource(self):
        rendered = subprocess.run(
            ["kustomize", "build", ROOT / "platform/automation/private-dns/control-d-only"],
            check=True, capture_output=True, text=True,
        )
        composition = json.loads(subprocess.run(
            ["yq", "-o=json", "."], input=rendered.stdout,
            check=True, capture_output=True, text=True,
        ).stdout)
        self.assertEqual(composition["metadata"]["name"], "private-dns-record-control-d-only")
        resources = composition["spec"]["pipeline"][0]["input"]["resources"]
        self.assertEqual(resources, [composition_resource(
            "platform/automation/private-dns/composition/composition.yaml",
            "control-d-rule", base=False,
        )])

    def test_each_cluster_discovers_its_own_tailscale_addresses(self):
        for cluster in ["mbk", "syd"]:
            with self.subTest(cluster=cluster):
                rendered = subprocess.run(
                    ["kustomize", "build", ROOT / "clusters" / cluster / "automation"],
                    check=True, capture_output=True, text=True,
                )
                result = subprocess.run(
                    ["yq", "-N", "-r", 'select(.kind == "Request") | .spec.forProvider.payload.baseUrl'],
                    input=rendered.stdout, check=True, capture_output=True, text=True,
                )
                self.assertEqual(set(result.stdout.splitlines()), {
                    f"https://cloudflare-dns.com/dns-query?name=private.{cluster}.excloo.dev&type={record_type}"
                    for record_type in ["A", "AAAA"]
                })


class CloudflareZoneTests(unittest.TestCase):
    def test_zone_lookup_requires_one_successful_matching_result(self):
        resource = composition_resource(
            "platform/automation/cloudflare/composition.yaml", "zone"
        )
        expression = resource["spec"]["forProvider"]["expectedResponseCheck"]["logic"]
        data = {
            "payload": {"body": {"zoneName": "example.com"}},
            "response": {"statusCode": 200, "body": {
                "success": True, "result": [{"id": "zone-id", "name": "example.com"}],
            }},
        }
        self.assertTrue(evaluate(expression, data))
        for response in [
            {"statusCode": 500, "body": {"success": False, "result": None}},
            {"statusCode": 200, "body": {"success": True, "result": []}},
            {"statusCode": 200, "body": {"success": True, "result": [{"name": "other.com"}]}},
            {"statusCode": 200, "body": {"success": True, "result": [{"name": "example.com"}] * 2}},
        ]:
            with self.subTest(response=response):
                self.assertFalse(evaluate(expression, dict(data, response=response)))


class B2ComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.resource = composition_resource(
            "platform/automation/b2/composition.yaml", "application-key", base=False
        )
        comparison = next(
            patch
            for patch in cls.resource["patches"]
            if patch["toFieldPath"] == "spec.forProvider.expectedResponseCheck.logic"
        )
        cls.expression = comparison["transforms"][0]["string"]["fmt"] % "beszel"
        cls.expression = cls.expression.replace("{{ b2-bucket:beszel:bucket-id }}", "bucket-id")

    def setUp(self):
        self.key = {
            "applicationKeyId": "key-id",
            "keyName": "kubelab-mbk-beszel",
            "bucketIds": ["bucket-id"],
            "capabilities": ["readFiles", "writeFiles"],
        }
        self.data = {
            "payload": {"body": dict(self.key, bucketIds=["{{ b2-bucket:beszel:bucket-id }}"])},
            "response": {"statusCode": 200, "body": {"keys": [self.key]}},
        }

    def test_authorisation_publishes_only_the_public_api_url(self):
        resource = composition_resource(
            "platform/automation/b2/composition.yaml", "authorisation", base=False
        )
        patch = next(
            patch for patch in resource["patches"]
            if patch["type"] == "ToCompositeFieldPath"
        )
        expression = patch["transforms"][0]["string"]["regexp"]
        response = {
            "accountId": "account",
            "authorizationToken": "private-token",
            "apiInfo": {"storageApi": {"apiUrl": "https://api005.backblazeb2.com"}},
        }
        self.assertEqual(patch["toFieldPath"], "status.apiUrl")
        for indent in [None, 2]:
            body = json.dumps(response, indent=indent)
            match = re.search(expression["match"], body)
            self.assertEqual(match.group(expression["group"]), "https://api005.backblazeb2.com")

    def test_existing_and_created_key_are_in_sync(self):
        self.assertTrue(evaluate(self.expression, self.data))
        self.data["response"]["body"] = self.key
        self.assertTrue(evaluate(self.expression, self.data))

    def test_duplicate_name_or_wrong_scope_is_out_of_sync(self):
        wrong_bucket = dict(self.key, bucketIds=["another-bucket"])
        wrong_permissions = dict(self.key, capabilities=["deleteBuckets"])
        for keys in [[], [self.key, wrong_bucket], [wrong_bucket], [wrong_permissions]]:
            with self.subTest(keys=keys):
                self.data["response"]["body"]["keys"] = keys
                self.assertFalse(evaluate(self.expression, self.data))

    def test_existing_name_cannot_create_another_key(self):
        mappings = self.resource["base"]["spec"]["forProvider"]["mappings"]
        expression = next(mapping["body"] for mapping in mappings if mapping["action"] == "UPDATE")
        with self.assertRaises(subprocess.CalledProcessError):
            evaluate(expression, self.data)
        self.data["response"]["body"]["keys"] = []
        self.assertEqual(evaluate(expression, self.data), self.data["payload"]["body"])


if __name__ == "__main__":
    unittest.main()
