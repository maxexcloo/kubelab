"""Check private workstation routes against their external backends."""

import unittest

from support import repository_resources


class WorkstationRouteTests(unittest.TestCase):
    def test_routes_keep_workstation_backends_on_the_private_gateway(self):
        resources = [
            resource
            for resource in repository_resources("apps/overlays/syd")
            if resource["metadata"].get("namespace") == "workstation-services"
        ]
        services = {
            resource["metadata"]["name"]: resource["spec"]
            for resource in resources
            if resource["kind"] == "Service"
        }
        endpoints = {
            resource["metadata"]["name"]: resource
            for resource in resources
            if resource["kind"] == "EndpointSlice"
        }
        dns = {
            resource["spec"]["hostname"]
            for resource in resources
            if resource["kind"] == "PrivateDNSRecord"
        }
        routes = {
            resource["metadata"]["name"]: resource["spec"]
            for resource in resources
            if resource["kind"] == "HTTPRoute"
        }
        expected = {
            f"{app}-{host}": (host, port)
            for app, port in (("agent-browser", 9222), ("syncthing", 8384))
            for host in ("mars", "mercury")
        }
        self.assertEqual(set(routes), set(expected))
        for name, (host, port) in expected.items():
            with self.subTest(route=name):
                route = routes[name]
                self.assertEqual(
                    route["parentRefs"],
                    [{"name": "private", "namespace": "networking"}],
                )
                self.assertEqual(
                    route["hostnames"],
                    [f"{name}.excloo.com", f"{name}.syd.excloo.dev"],
                )
                self.assertIn(route["hostnames"][0], dns)
                self.assertEqual(
                    route["rules"],
                    [{"backendRefs": [{"name": host, "port": port}]}],
                )
                service = services[host]
                self.assertNotIn("selector", service)
                service_port = next(p for p in service["ports"] if p["port"] == port)
                endpoint = endpoints[host]
                self.assertEqual(
                    endpoint["metadata"]["labels"]["kubernetes.io/service-name"],
                    host,
                )
                self.assertIn(
                    {"name": service_port["name"], "port": port, "protocol": "TCP"},
                    endpoint["ports"],
                )
                self.assertEqual(endpoint["addressType"], "IPv4")
                self.assertTrue(endpoint["endpoints"][0]["addresses"])
