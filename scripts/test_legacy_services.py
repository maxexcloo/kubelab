#!/usr/bin/env python3

import json
import re
import subprocess
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent

APPLICATIONS = {
    "actual-budget": "apps/base/actual-budget",
    "aiometadata": "apps/base/aiometadata",
    "aiostreams": "apps/base/aiostreams",
    "anisette": "apps/base/anisette",
    "beszel": "apps/base/beszel",
    "beszel-agent": "apps/base/beszel-agent",
    "bichon": "apps/base/bichon",
    "bookorbit": "apps/base/bookorbit",
    "byparr": "apps/base/byparr",
    "homepage": "apps/base/homepage",
    "immich": "apps/base/immich",
    "larapaper": "apps/base/larapaper",
    "linkwarden": "apps/base/linkwarden",
    "miniflux": "apps/base/miniflux",
    "open-webui": "apps/base/open-webui",
    "openspeedtest": "apps/base/openspeedtest",
    "papra": "apps/base/papra",
    "pocket-id": "apps/base/pocket-id",
    "redlib": "apps/base/redlib",
    "romm": "apps/base/romm",
    "romm-workflows": "apps/base/romm",
    "shelfarr": "apps/base/shelfmark",
}
PLATFORM = {
    "cloudflared": "platform/networking/cloudflared",
    "tailscale": "platform/networking/tailscale",
    "traefik": "platform/networking/traefik",
}
RETAINED = {"gatus", "netbootxyz", "syncthing"}
RETIRED = {"dozzle", "dozzle-agent", "github-runner", "oauth2-proxy"}
LEGACY_SERVICES = set(APPLICATIONS) | set(PLATFORM) | RETAINED | RETIRED
LEGACY_ROUTE_HOSTS = {
    "anisette.excloo.com",
    "books.excloo.com",
    "budget.excloo.com",
    "chat.excloo.com",
    "doco-cd.hsp.au.excloo.net",
    "docs.excloo.com",
    "games.excloo.com",
    "home-assistant.excloo.com",
    "home.excloo.com",
    "id.excloo.com",
    "larapaper.excloo.com",
    "photos.excloo.com",
    "reader.excloo.com",
    "reddit.excloo.com",
    "shelf.excloo.com",
    "status.excloo.com",
}

REDLIB_SUBSCRIPTIONS = [
    "anime_titties",
    "apple",
    "askanaustralian",
    "askhistorians",
    "askscience",
    "auscorp",
    "ausfinance",
    "auspropertychat",
    "aussiefrugal",
    "australia",
    "australiannostalgia",
    "bazzite",
    "boxoffice",
    "budgetaudiophile",
    "cars",
    "carsaustralia",
    "catastrophicfailure",
    "chatgptcoding",
    "crackwatch",
    "cscareerquestionsoce",
    "datahoarder",
    "deepseek",
    "docker",
    "eink",
    "electricvehicles",
    "emulation",
    "emulationonandroid",
    "esphome",
    "flashlight",
    "flipperzero",
    "games",
    "handhelds",
    "hardware",
    "homeassistant",
    "homelab",
    "homenetworking",
    "homeserver",
    "immich",
    "internetisbeautiful",
    "korea",
    "linux",
    "linux_gaming",
    "linuxhardware",
    "living_in_korea",
    "llmdevs",
    "localllama",
    "localllm",
    "meshcore",
    "minilab",
    "minimalism",
    "minipcs",
    "moonlightstreaming",
    "movies",
    "nbn",
    "netsec",
    "networking",
    "nixos",
    "odinhandheld",
    "onebag",
    "opencode",
    "opensource",
    "openwrt",
    "organizationporn",
    "outoftheloop",
    "pikvm",
    "piratedgames",
    "praisethecameraman",
    "privacy",
    "programming",
    "proxmox",
    "raspberry_pi",
    "retroarch",
    "retroid",
    "roms",
    "sbcgaming",
    "sbcs",
    "selfhosted",
    "sffpc",
    "sideloaded",
    "singularity",
    "solotravel",
    "space",
    "steamdeck",
    "sydney",
    "sydneyscene",
    "sydneytrains",
    "sysadmin",
    "tailscale",
    "television",
    "thatlookedexpensive",
    "trance",
    "travel",
    "travelhacks",
    "trimui",
    "truenas",
    "ubiquiti",
    "usbchardware",
    "wallstreetbets",
    "wled",
    "zfs",
    "zigbee",
]


def rendered_resources(path):
    manifests = subprocess.run(
        ["kustomize", "build", path],
        check=True,
        capture_output=True,
        cwd=REPOSITORY_ROOT,
        text=True,
    ).stdout
    resources = subprocess.run(
        ["yq", "eval-all", "-o=json", "-I=0", "[select(.kind != null)]", "-"],
        check=True,
        capture_output=True,
        cwd=REPOSITORY_ROOT,
        input=manifests,
        text=True,
    ).stdout
    return json.loads(resources)


def resource_by_name(resources, kind, name):
    return next(
        resource
        for resource in resources
        if resource["kind"] == kind and resource["metadata"]["name"] == name
    )


def jq(program, value):
    result = subprocess.run(
        ["jq", "-c", program],
        check=True,
        capture_output=True,
        input=json.dumps(value),
        text=True,
    ).stdout
    return json.loads(result)


class LegacyServiceTests(unittest.TestCase):
    def test_all_legacy_services_have_one_explicit_disposition(self):
        self.assertEqual(len(LEGACY_SERVICES), 32)
        self.assertEqual(
            (set(APPLICATIONS) & set(PLATFORM))
            | (set(APPLICATIONS) & RETAINED)
            | (set(APPLICATIONS) & RETIRED)
            | (set(PLATFORM) & RETAINED)
            | (set(PLATFORM) & RETIRED)
            | (RETAINED & RETIRED),
            set(),
        )
        for path in set(APPLICATIONS.values()) | set(PLATFORM.values()):
            self.assertTrue((REPOSITORY_ROOT / path / "kustomization.yaml").is_file())
        inventory = (REPOSITORY_ROOT / "docs/legacy-services.md").read_text()
        for service in LEGACY_SERVICES:
            self.assertRegex(inventory, rf"(?m)^\|\s*`{re.escape(service)}`\s*\|")
        self.assertRegex(
            inventory,
            r"(?m)^\|\s*`gatus`\s*\|\s*Retain\s*\|.*`homelab-fly`",
        )
        self.assertEqual(len(LEGACY_ROUTE_HOSTS), 16)
        for hostname in LEGACY_ROUTE_HOSTS:
            self.assertRegex(inventory, rf"(?m)^\|\s*`{re.escape(hostname)}`\s*\|")

    def test_b2_adopts_bucket_and_observes_nonrecoverable_key(self):
        beszel = rendered_resources("apps/base/beszel")
        object_storage = resource_by_name(
            beszel, "ExternalSecret", "beszel-object-storage"
        )
        annotations = object_storage["metadata"]["annotations"]
        self.assertEqual(
            annotations["onepassword.excloo.dev/adopt-titles"], "Beszel (beszel)"
        )
        self.assertEqual(
            json.loads(annotations["onepassword.excloo.dev/migrate-fields"]),
            {
                "object_storage_access_key_id_ro": "object-storage-access-key-id",
                "object_storage_bucket_ro": "object-storage-bucket",
                "object_storage_endpoint_ro": "object-storage-endpoint",
                "object_storage_secret_access_key_ro": "object-storage-secret-access-key",
            },
        )

        resources = rendered_resources("apps/integrations/b2")
        authorisation = resource_by_name(resources, "Request", "b2-authorisation")
        bucket = resource_by_name(resources, "Request", "b2-beszel-bucket")
        key = resource_by_name(resources, "Request", "b2-beszel-key")
        self.assertEqual(authorisation["spec"]["managementPolicies"], ["Observe"])
        self.assertEqual(
            bucket["spec"]["managementPolicies"],
            ["LateInitialize", "Observe", "Update"],
        )
        self.assertEqual(key["spec"]["managementPolicies"], ["Observe"])
        for resource in resources:
            actions = {
                mapping["action"]
                for mapping in resource["spec"]["forProvider"]["mappings"]
            }
            self.assertNotIn("REMOVE", actions)
        authorisation_check = authorisation["spec"]["forProvider"][
            "expectedResponseCheck"
        ]["logic"]
        self.assertTrue(
            jq(
                authorisation_check,
                {
                    "response": {
                        "body": {
                            "accountId": "account-id",
                            "apiInfo": {
                                "storageApi": {
                                    "apiUrl": "https://api005.backblazeb2.com",
                                    "s3ApiUrl": "https://s3.us-east-005.backblazeb2.com",
                                }
                            },
                            "authorizationToken": "session-token",
                        },
                        "statusCode": 200,
                    }
                },
            )
        )
        bucket_check = bucket["spec"]["forProvider"]["expectedResponseCheck"]["logic"]
        self.assertIn('algorithm == "AES256"', bucket_check)
        self.assertIn('mode == "SSE-B2"', bucket_check)
        self.assertIn('"daysFromHidingToDeleting": 1', bucket_check)
        bucket_id = "bucket-id"
        bucket_response = {
            "buckets": [
                {
                    "bucketId": bucket_id,
                    "bucketType": "allPrivate",
                    "defaultServerSideEncryption": {
                        "isClientAuthorizedToRead": True,
                        "value": {"algorithm": "AES256", "mode": "SSE-B2"},
                    },
                    "lifecycleRules": [
                        {
                            "daysFromHidingToDeleting": 1,
                            "daysFromUploadingToHiding": None,
                            "fileNamePrefix": "",
                        }
                    ],
                }
            ]
        }
        self.assertTrue(
            jq(
                bucket_check,
                {"response": {"body": bucket_response, "statusCode": 200}},
            )
        )
        bucket_mappings = {
            mapping["action"]: mapping
            for mapping in bucket["spec"]["forProvider"]["mappings"]
        }
        update = jq(
            bucket_mappings["UPDATE"]["body"],
            {
                "payload": {"body": {"accountId": "account-id"}},
                "response": {"body": bucket_response},
            },
        )
        self.assertEqual(update["accountId"], "account-id")
        self.assertEqual(update["bucketId"], bucket_id)
        self.assertEqual(update["bucketType"], "allPrivate")
        key_check = key["spec"]["forProvider"]["expectedResponseCheck"]["logic"]
        for capability in (
            "deleteFiles",
            "listBuckets",
            "listFiles",
            "readBuckets",
            "readFiles",
            "shareFiles",
            "writeFiles",
        ):
            self.assertIn(f'"{capability}"', key_check)
        access_key_id = "access-key-id"
        key_check = key_check.replace(
            "{{ beszel-object-storage:beszel:access-key-id }}", access_key_id
        ).replace("{{ b2-beszel-inventory:beszel:bucket-id }}", bucket_id)
        self.assertTrue(
            jq(
                key_check,
                {
                    "response": {
                        "body": {
                            "keys": [
                                {
                                    "applicationKeyId": access_key_id,
                                    "bucketId": bucket_id,
                                    "capabilities": [
                                        "deleteFiles",
                                        "listBuckets",
                                        "listFiles",
                                        "readBuckets",
                                        "readFiles",
                                        "shareFiles",
                                        "writeFiles",
                                    ],
                                    "keyName": "beszel",
                                }
                            ]
                        },
                        "statusCode": 200,
                    }
                },
            )
        )
        cluster = resource_by_name(
            rendered_resources("clusters/mbk"), "Kustomization", "b2-automation"
        )
        self.assertTrue(cluster["spec"]["suspend"])

    def test_cloudflare_update_preserves_unrelated_rules_and_masks_token(self):
        resources = rendered_resources("platform/automation/cloudflare")
        composition = resource_by_name(resources, "Composition", "redlib-waf-policy")
        composed = {
            resource["name"]: resource
            for resource in composition["spec"]["pipeline"][0]["input"]["resources"]
        }
        zone = composed["zone"]
        waf = composed["waf"]
        zone_request = zone["base"]
        zone_mapping = zone_request["spec"]["forProvider"]["secretInjectionConfigs"][
            0
        ]["keyMappings"][0]
        self.assertEqual(zone_mapping["responseJQ"], ".body.result[0].id")
        zone_id = "a" * 32
        zone_context = {
            "payload": {"body": {"zoneName": "excloo.com"}},
            "response": {
                "body": {
                    "result": [
                        {
                            "account": {"id": "b" * 32},
                            "id": zone_id,
                            "name": "excloo.com",
                        }
                    ],
                    "success": True,
                },
                "statusCode": 200,
            },
        }
        self.assertEqual(jq(zone_mapping["responseJQ"], zone_context["response"]), zone_id)
        zone_check = zone_request["spec"]["forProvider"]["expectedResponseCheck"][
            "logic"
        ]
        self.assertTrue(jq(zone_check, zone_context))

        request = waf["base"]
        self.assertIn(
            "{{ cloudflare-zone-inventory:crossplane-system:zone-id }}",
            request["spec"]["forProvider"]["payload"]["baseUrl"],
        )
        policies = request["spec"]["managementPolicies"]
        self.assertEqual(policies, ["Create", "LateInitialize", "Observe", "Update"])
        mappings = {
            mapping["action"]: mapping
            for mapping in request["spec"]["forProvider"]["mappings"]
        }
        self.assertEqual(set(mappings), {"CREATE", "OBSERVE", "UPDATE"})
        payload = json.loads(request["spec"]["forProvider"]["payload"]["body"])
        token_placeholder = "{{ redlib-waf-credentials:crossplane-system:monitoring-token }}"
        token = "retained-gatus-token"
        legacy_rule = dict(payload["rule"])
        legacy_rule.pop("ref")
        legacy_rule["description"] = ""
        legacy_rule["expression"] = legacy_rule["expression"].replace(
            token_placeholder, token
        )
        unrelated = {
            "action": "block",
            "description": "Unrelated",
            "enabled": True,
            "expression": "ip.src eq 192.0.2.1",
            "id": "unrelated-id",
            "last_updated": "2026-01-01T00:00:00Z",
            "ref": "unrelated",
            "version": "3",
        }
        context = {
            "payload": {"body": payload},
            "response": {
                "body": {
                    "result": {
                        "description": "Existing rules",
                        "rules": [unrelated, legacy_rule],
                    }
                }
            },
        }
        update = jq(mappings["UPDATE"]["body"], context)
        self.assertEqual(len(update["rules"]), 2)
        self.assertEqual(update["rules"][0]["ref"], "unrelated")
        self.assertNotIn("id", update["rules"][0])
        self.assertEqual(update["rules"][1], payload["rule"])

        response_jq = request["spec"]["forProvider"]["secretInjectionConfigs"][0][
            "keyMappings"
        ][0]["responseJQ"]
        observed = jq(
            response_jq,
            {"body": {"result": {"rules": [unrelated, legacy_rule]}}},
        )
        self.assertEqual(observed, token)
        current_rule = payload["rule"] | {
            "expression": payload["rule"]["expression"].replace(
                token_placeholder, token
            )
        }
        expected_response = request["spec"]["forProvider"]["expectedResponseCheck"][
            "logic"
        ].replace(token_placeholder, token)
        self.assertTrue(
            jq(
                expected_response,
                {
                    "response": {
                        "body": {
                            "result": {
                                "rules": [unrelated, current_rule]
                            },
                            "success": True,
                        },
                        "statusCode": 200,
                    }
                },
            )
        )
        cluster = resource_by_name(
            rendered_resources("clusters/mbk"),
            "Kustomization",
            "cloudflare-automation",
        )
        self.assertTrue(cluster["spec"]["suspend"])

    def test_home_assistant_webhook_route_is_staged_and_tls_validated(self):
        resources = rendered_resources("apps/integrations/home-assistant")
        endpoint = resource_by_name(resources, "EndpointSlice", "home-assistant")
        policy = resource_by_name(resources, "BackendTLSPolicy", "home-assistant")
        route = resource_by_name(resources, "HTTPRoute", "home-assistant-webhook")
        service = resource_by_name(resources, "Service", "home-assistant")
        self.assertEqual(endpoint["endpoints"][0]["addresses"], ["10.0.0.2"])
        self.assertNotIn("selector", service["spec"])
        self.assertEqual(policy["spec"]["targetRefs"][0]["sectionName"], "https")
        self.assertEqual(policy["spec"]["validation"]["hostname"], "hass.mbk.excloo.net")
        self.assertEqual(
            policy["spec"]["validation"]["wellKnownCACertificates"], "System"
        )
        self.assertEqual(route["spec"]["hostnames"], ["home-assistant.excloo.com"])
        self.assertEqual(
            route["spec"]["rules"][0]["matches"][0]["path"],
            {"type": "PathPrefix", "value": "/api/webhook"},
        )
        self.assertNotIn("gethomepage.dev/enabled", route["metadata"]["annotations"])
        cluster = resource_by_name(
            rendered_resources("clusters/mbk"),
            "Kustomization",
            "home-assistant-webhook",
        )
        self.assertTrue(cluster["spec"]["suspend"])

    def test_homepage_retains_external_services_and_provider_bookmarks(self):
        resources = rendered_resources("apps/base/homepage")
        configuration = resource_by_name(resources, "ConfigMap", "homepage")["data"]
        for name in (
            "Gatus",
            "Home Assistant",
            "Netboot",
            "Syncthing",
            "TrueNAS",
            "UniFi",
        ):
            self.assertIn(f"{name}:", configuration["services.yaml"])
        for provider in (
            "1Password",
            "Backblaze",
            "Cloudflare",
            "Control D",
            "Fly.io",
            "GitHub",
            "Oracle Cloud",
            "Resend",
            "Tailscale",
            "UniFi",
        ):
            self.assertIn(f"{provider}:", configuration["bookmarks.yaml"])
        settings = configuration["settings.yaml"]
        self.assertIn("Applications:\n    columns: 4", settings)
        self.assertIn("Infrastructure:\n    columns: 2", settings)

    def test_linkwarden_namespace_allows_both_declared_routes(self):
        resources = rendered_resources("apps/base/linkwarden")
        namespace = resource_by_name(resources, "Namespace", "linkwarden")
        release = resource_by_name(resources, "HelmRelease", "linkwarden")
        labels = namespace["metadata"]["labels"]
        routes = release["spec"]["values"]["route"]
        self.assertEqual(set(routes), {"private", "public"})
        self.assertEqual(labels["gateway.excloo.dev/private-access"], "true")
        self.assertEqual(labels["gateway.excloo.dev/public-access"], "true")

    def test_redlib_defaults_match_legacy_and_credentials_are_adopted(self):
        resources = rendered_resources("apps/base/redlib")
        release = resource_by_name(resources, "HelmRelease", "redlib")
        subscriptions = release["spec"]["values"]["controllers"]["redlib"][
            "containers"
        ]["redlib"]["env"]["REDLIB_DEFAULT_SUBSCRIPTIONS"].split("+")
        self.assertEqual(subscriptions, REDLIB_SUBSCRIPTIONS)
        secret = resource_by_name(resources, "ExternalSecret", "redlib")
        annotations = secret["metadata"]["annotations"]
        self.assertEqual(annotations["onepassword.excloo.dev/adopt-titles"], "Redlib (redlib)")
        migration = json.loads(
            annotations["onepassword.excloo.dev/migrate-fields"]
        )
        self.assertEqual(migration["monitoring_token_rw"], "monitoring-token")

    def test_staged_workloads_are_suspended_and_private_only(self):
        for application in (
            "aiometadata",
            "aiostreams",
            "open-webui",
            "pocket-id",
            "romm",
        ):
            resources = rendered_resources(f"apps/base/{application}")
            namespace = resource_by_name(resources, "Namespace", application)
            labels = namespace["metadata"]["labels"]
            self.assertEqual(labels["gateway.excloo.dev/private-access"], "true")
            self.assertNotIn("gateway.excloo.dev/public-access", labels)

            release = resource_by_name(resources, "HelmRelease", application)
            self.assertTrue(release["spec"]["suspend"])
            route = release["spec"]["values"]["route"]
            if "main" in route:
                route = route["main"]
            self.assertEqual(
                route["parentRefs"],
                [{"name": "private", "namespace": "networking"}],
            )
            self.assertNotIn(
                "external-dns.alpha.kubernetes.io/hostname",
                route.get("annotations", {}),
            )

    def test_suspended_staging_resources_do_not_block_parent_health(self):
        cluster = rendered_resources("clusters/mbk")
        root = resource_by_name(cluster, "Kustomization", "flux-system")
        applications = resource_by_name(cluster, "Kustomization", "apps")
        expected = {
            "current": (
                "(has(spec.suspend) && spec.suspend) || "
                "status.conditions.exists(e, e.type == 'Ready' "
                "&& e.status == 'True' && e.observedGeneration == metadata.generation)"
            ),
            "failed": (
                "(!has(spec.suspend) || !spec.suspend) && "
                "status.conditions.exists(e, e.type == 'Ready' "
                "&& e.status == 'False' && e.observedGeneration == metadata.generation)"
            ),
        }
        root_check = next(
            expression
            for expression in root["spec"]["healthCheckExprs"]
            if expression["kind"] == "Kustomization"
        )
        application_check = next(
            expression
            for expression in applications["spec"]["healthCheckExprs"]
            if expression["kind"] == "HelmRelease"
        )
        for check in (application_check, root_check):
            self.assertEqual(check["current"], expected["current"])
            self.assertEqual(check["failed"], expected["failed"])


if __name__ == "__main__":
    unittest.main()
