"""Exercise API comparisons with responses, independently of live services."""

import copy
import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def composition_resource(path, name, *, base=True):
    result = subprocess.run(
        [
            "yq", "-o=json",
            'select(.kind == "Composition") | .spec.pipeline[0].input.resources[] '
            f'| select(.name == "{name}")' + (' | .base' if base else ''),
            ROOT / path,
        ],
        check=True, capture_output=True, text=True,
    )
    return json.loads(result.stdout)


def evaluate(expression, data):
    result = subprocess.run(
        ["jq", "-c", expression], input=json.dumps(data),
        check=True, capture_output=True, text=True,
    )
    return json.loads(result.stdout)


class PrivateDNSComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        resource = composition_resource(
            "platform/automation/private-dns/private-dns-record.yaml", "control-d-rule"
        )
        # The provider resolves placeholders in the expression, not in payload.
        cls.expression = resource["spec"]["forProvider"]["expectedResponseCheck"]["logic"]
        cls.expression = cls.expression.replace(
            "{{ private-dns-target-ipv4:crossplane-system:address }}", "100.64.0.1"
        ).replace("{{ private-dns-target-ipv6:crossplane-system:address }}", "fd00::1")

    def setUp(self):
        self.data = {
            "payload": {"body": {
                "hostname": "reader.example.com",
                "ipv4": "{{ private-dns-target-ipv4:crossplane-system:address }}",
                "ipv6": "{{ private-dns-target-ipv6:crossplane-system:address }}",
            }},
            "response": {"statusCode": 200, "body": {"body": {"rules": [{
                "PK": "reader.example.com",
                "action": {"do": 2, "status": 1, "via": "100.64.0.1", "via_v6": "fd00::1"},
            }]}}},
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

    def test_api_error_is_out_of_sync(self):
        self.data["response"] = {"statusCode": 403, "body": {"error": "forbidden"}}
        self.assertFalse(evaluate(self.expression, self.data))


class B2ComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.resource = composition_resource(
            "platform/automation/b2/b2-object-storage.yaml", "application-key", base=False
        )
        comparison = next(
            patch for patch in cls.resource["patches"]
            if patch["toFieldPath"] == "spec.forProvider.expectedResponseCheck.logic"
        )
        cls.expression = comparison["transforms"][0]["string"]["fmt"] % "beszel"
        cls.expression = cls.expression.replace("{{ b2-bucket:beszel:bucket-id }}", "bucket-id")

    def setUp(self):
        self.key = {
            "applicationKeyId": "key-id", "keyName": "kubelab-mbk-beszel",
            "bucketIds": ["bucket-id"], "capabilities": ["readFiles", "writeFiles"],
        }
        self.data = {
            "payload": {"body": dict(self.key, bucketIds=["{{ b2-bucket:beszel:bucket-id }}"])},
            "response": {"statusCode": 200, "body": {"keys": [self.key]}},
        }

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
