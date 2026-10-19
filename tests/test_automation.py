"""Exercise API comparisons with responses, independently of live services."""

import copy
import json
import re
import subprocess
import unittest
from pathlib import Path

from support import CLUSTERS, read_resources


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


class ResendIdentityTests(unittest.TestCase):
    def test_publishing_uses_the_existing_item_title_and_retains_the_api_key_identity(self):
        publisher = composition_resource(
            "platform/automation/resend/composition.yaml", "onepassword-item", base=False
        )
        patch = next(p for p in publisher["patches"] if p.get("toFieldPath") == "spec.data[0].match.remoteRef.remoteKey")
        self.assertEqual(patch["fromFieldPath"], "spec.item")
        self.assertEqual(patch["policy"]["fromFieldPath"], "Required")
        key = composition_resource(
            "platform/automation/resend/composition.yaml", "api-key", base=False
        )
        naming = next(p for p in key["patches"] if p.get("toFieldPath") == "spec.forProvider.payload.body")
        self.assertEqual([v["fromFieldPath"] for v in naming["combine"]["variables"]], ["spec.cluster", "metadata.namespace"])


class PocketIDClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.resource = composition_resource(
            "platform/automation/pocket-id/composition.yaml", "client", base=False
        )
        cls.parameters = cls.resource["base"]["spec"]["forProvider"]

    def test_creation_retains_the_registered_client_id_and_callbacks(self):
        client = {
            "id": "headlamp", "name": "Headlamp", "isPublic": True,
            "pkceEnabled": True,
            "callbackURLs": ["https://dashboard.example/oidc-callback"],
        }
        mapping = next(m for m in self.parameters["mappings"] if m["action"] == "CREATE")
        self.assertEqual(evaluate(mapping["body"], {"payload": {"body": client}}), client)

    def test_clients_can_be_created_but_never_deleted(self):
        self.assertIn("Create", self.resource["base"]["spec"]["managementPolicies"])
        self.assertNotIn("Delete", self.resource["base"]["spec"]["managementPolicies"])
        secret = composition_resource(
            "platform/automation/pocket-id/composition.yaml", "client-secret", base=False
        )
        self.assertEqual(secret["base"]["spec"]["managementPolicies"], ["Create", "Observe"])

    def test_requests_stay_beside_the_pocket_id_api_key(self):
        for name in ["client", "client-secret", "group-access", "onepassword-item"]:
            resource = composition_resource(
                "platform/automation/pocket-id/composition.yaml", name, base=False
            )
            self.assertEqual(resource["base"]["metadata"]["namespace"], "pocket-id")
            self.assertNotIn(
                "metadata.namespace",
                [patch.get("toFieldPath") for patch in resource["patches"]],
            )

    def test_only_confidential_clients_publish_a_secret(self):
        for name in ["client-secret", "onepassword-item"]:
            resource = composition_resource(
                "platform/automation/pocket-id/composition.yaml", name, base=False
            )
            gate = next(p for p in resource["patches"] if p.get("fromFieldPath") == "spec.item")
            self.assertEqual(gate["policy"]["fromFieldPath"], "Required")

    def test_secret_is_created_until_a_create_succeeds(self):
        secret = composition_resource(
            "platform/automation/pocket-id/composition.yaml", "client-secret", base=False
        )
        mapping = next(
            m for m in secret["base"]["spec"]["forProvider"]["mappings"]
            if m["action"] == "OBSERVE"
        )
        payload = {"baseUrl": "https://id.example/api/oidc/clients/app/secrets"}
        for response, url in [
            ({}, None),
            ({"statusCode": 404}, None),
            ({"statusCode": 201}, payload["baseUrl"]),
            ({"statusCode": 200}, payload["baseUrl"]),
        ]:
            with self.subTest(response=response):
                self.assertEqual(
                    evaluate(mapping["url"], {"payload": payload, "response": response}), url
                )

    def test_public_client_response_detects_callback_and_pkce_drift(self):
        client = {
            "accessTokenDurationMinutes": 60,
            "callbackURLs": ["https://dashboard.example/oidc-callback"],
            "description": "Kubernetes Dashboard", "isGroupRestricted": True,
            "isPublic": True, "launchURL": "https://dashboard.example",
            "logoutCallbackURLs": [], "name": "Headlamp", "pkceEnabled": True,
            "refreshTokenDurationMinutes": 43200,
            "requiresPushedAuthorizationRequests": False,
            "requiresReauthentication": False, "skipConsent": False,
        }
        data = {"payload": {"body": client},
                "response": {"statusCode": 200, "body": dict(client, id="headlamp")}}
        expression = self.parameters["expectedResponseCheck"]["logic"]
        self.assertTrue(evaluate(expression, data))
        for key, value in (("callbackURLs", []), ("pkceEnabled", False), ("isPublic", False)):
            changed = copy.deepcopy(data)
            changed["response"]["body"][key] = value
            self.assertFalse(evaluate(expression, changed))


class PrivateDNSTargetDiscoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        resource = next(
            resource for resource in read_resources(
                ROOT / "platform/automation/private-dns/target-discovery.yaml"
            ) if resource["metadata"]["name"] == "private-dns-target-ipv6"
        )
        cls.parameters = resource["spec"]["forProvider"]

    def test_absent_and_present_ipv6_answers_have_defined_targets(self):
        mapping = self.parameters["secretInjectionConfigs"][0]["keyMappings"][0]["responseJQ"]
        for answers, target in [
            ([], "::"),
            ([{"type": 5, "data": "target.example"}], "::"),
            ([{"type": 28, "data": "fd00::1"}], "fd00::1"),
        ]:
            with self.subTest(answers=answers):
                body = {"Answer": answers, "Status": 0}
                response = {"response": {"body": body, "statusCode": 200}}
                self.assertTrue(evaluate(self.parameters["expectedResponseCheck"]["logic"], response))
                self.assertEqual(evaluate(mapping, {"body": body}), target)

    def test_failed_and_ambiguous_dns_responses_are_rejected(self):
        expression = self.parameters["expectedResponseCheck"]["logic"]
        for response in [
            {"body": {"Status": 0}, "statusCode": 503},
            {"body": {"Status": 3}, "statusCode": 200},
            {"body": {"Answer": [
                {"type": 28, "data": "fd00::1"},
                {"type": 28, "data": "fd00::2"},
            ], "Status": 0}, "statusCode": 200},
        ]:
            with self.subTest(response=response):
                self.assertFalse(evaluate(expression, {"response": response}))


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
            ["kubectl", "kustomize", ROOT / "platform/automation/private-dns/control-d-only"],
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
        for cluster in CLUSTERS:
            with self.subTest(cluster=cluster):
                rendered = subprocess.run(
                    ["kubectl", "kustomize", ROOT / "clusters" / cluster / "automation"],
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
    def test_bucket_lifecycle_accepts_null_api_defaults_but_detects_changes(self):
        resource = composition_resource(
            "platform/automation/b2/composition.yaml", "bucket"
        )
        expression = resource["spec"]["forProvider"]["expectedResponseCheck"]["logic"]
        rule = {"daysFromHidingToDeleting": 1, "fileNamePrefix": ""}
        bucket = {
            "bucketType": "allPrivate",
            "defaultServerSideEncryption": {
                "isClientAuthorizedToRead": True,
                "value": {"algorithm": "AES256", "mode": "SSE-B2"},
            },
            "lifecycleRules": [rule],
        }
        for listed in [False, True]:
            data = {"response": {"statusCode": 200, "body":
                    {"buckets": [bucket]} if listed else bucket}}
            with self.subTest(listed=listed):
                self.assertTrue(evaluate(expression, data))
                for key in ["daysFromUploadingToHiding", "daysFromStartingToCancelingUnfinishedLargeFiles"]:
                    rule[key] = None
                    self.assertTrue(evaluate(expression, data))
                    rule[key] = 2
                    self.assertFalse(evaluate(expression, data))
                    del rule[key]

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
            "keyName": "kubelab-syd-beszel",
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
