"""Exercise the rendered remote HA rule separately from LAN and webhook access."""

import json
import unittest

from support import repository_resources


class HomeAssistantAccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        resources = repository_resources("apps/overlays/syd")
        cls.policy = next(resource for resource in resources
                          if resource["kind"] == "CloudflareWAFPolicy"
                          and resource["metadata"]["namespace"] == "home-assistant")

    def blocked(self, host, verified=False, revoked=False, path="/"):
        # Evaluate this rule's boolean fields using fixture values, not live TLS.
        expression = self.policy["spec"]["rule"]["expression"]
        for field, value in {
            "http.host": host,
            "http.request.uri.path": path,
            "cf.tls_client_auth.cert_verified": verified,
            "cf.tls_client_auth.cert_revoked": revoked,
        }.items():
            expression = expression.replace(field, repr(value))
        expression = expression.replace(" eq ", " == ")
        return eval(expression, {"__builtins__": {}}, {})

    def test_missing_invalid_expired_and_revoked_certificates_are_blocked(self):
        self.assertEqual(self.policy["spec"]["zoneName"], "excloo.com")
        rule = self.policy["spec"]["rule"]
        self.assertEqual(rule["ref"], "homelab-hass-mtls")
        self.assertEqual(rule["action"], "block")
        self.assertTrue(rule["enabled"])
        for path in ("/", "/auth/authorize", "/api/", "/api/websocket",
                     "/api/webhook/example", "/local/example.js"):
            for state, verified, revoked, blocked in (
                ("absent", False, False, True),
                ("untrusted", False, False, True),
                ("expired", False, False, True),
                ("valid", True, False, False),
                # Cloudflare still reports cert_verified=true after revocation.
                ("revoked", True, True, True),
            ):
                with self.subTest(path=path, state=state):
                    self.assertEqual(self.blocked("remote-hass.excloo.com", verified,
                                                  revoked, path), blocked)

    def test_lan_webhooks_and_other_apps_do_not_require_a_client_certificate(self):
        for host in ("hass.mbk.excloo.net", "home-assistant.excloo.com", "id.excloo.com"):
            for verified, revoked in ((False, False), (True, False), (True, True)):
                with self.subTest(host=host, verified=verified, revoked=revoked):
                    self.assertFalse(self.blocked(host, verified, revoked))

    def test_no_new_proxy_route_or_public_dns_is_created_in_kubelab(self):
        resources = repository_resources("apps/overlays/syd")
        owned = [resource for resource in resources
                 if resource["metadata"].get("namespace") == "home-assistant"]
        self.assertEqual([resource["kind"] for resource in owned], ["CloudflareWAFPolicy"])
        self.assertNotIn("http.request.uri.path", json.dumps(self.policy))


if __name__ == "__main__":
    unittest.main()
