"""Shared fixtures for Homepage dashboard integration tests."""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from support import ROOT, read_yaml

APP = ROOT / "apps/base/homepage"
HOMELAB = ROOT / "tests/fixtures/homepage/homelab"


def route(name, **annotations):
    return {
        "apiVersion": "gateway.networking.k8s.io/v1",
        "kind": "HTTPRoute",
        "metadata": {
            "name": name.lower(),
            "namespace": name.lower(),
            "annotations": {
                "gethomepage.dev/enabled": "true",
                "gethomepage.dev/group": "Applications",
                "gethomepage.dev/href": f"https://{name.lower()}.example.net",
                "gethomepage.dev/name": name,
                **{
                    f"gethomepage.dev/{key}": value
                    for key, value in annotations.items()
                },
            },
        },
    }


def beszel_route():
    beszel = route(
        "Beszel",
        description="System Monitoring",
        icon="sh-beszel",
        **{
            "widget.password": '{{ "{{HOMEPAGE_VAR_BESZEL_PASSWORD}}" }}',
            "widget.type": "beszel",
            "widget.url": "https://beszel.example.net",
            "widget.username": '{{ "{{HOMEPAGE_VAR_BESZEL_USERNAME}}" }}',
            "widget.version": "2",
        },
    )
    beszel["metadata"]["namespace"] = "beszel"
    return beszel


class HomepageDashboardFixture:
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.output = self.directory / "output"
        self.placements = self.directory / "placements.json"
        self.placements.write_text("{}")
        self.queries = self.directory / "queries.jsonl"
        self.gatus = self.directory / "gatus.json"
        self.gatus.write_text(
            json.dumps(
                [
                    {
                        "group": "Providers",
                        "key": "providers_example",
                        "name": "Example",
                        "results": [{"duration": 12000000, "success": True}],
                    },
                ]
            )
        )
        self.kubectl = self.directory / "kubectl"
        self.kubectl.write_text("""#!/usr/bin/env python3
import json
import os
import sys
if sys.argv[1:2] == ["--namespace"] and sys.argv[3:5] == ["get", "pods"]:
    with open(os.environ["POD_QUERIES"], "a") as output:
        output.write(json.dumps(sys.argv[1:]) + "\\n")
    with open(os.environ["POD_PLACEMENTS"]) as source:
        placements = json.load(source)
        nodes = placements.get(sys.argv[2] + "/" + sys.argv[-1], placements.get(sys.argv[2], ["node"]))
    if nodes == "fail":
        sys.exit(1)
    print("\\n".join(nodes))
else:
    os.execv(os.environ["SYSTEM_KUBECTL"], [os.environ["SYSTEM_KUBECTL"], *sys.argv[1:]])
""")
        self.kubectl.chmod(0o755)
        for cluster in ("mbk", "syd"):
            for target in (f"apps/overlays/{cluster}", f"clusters/{cluster}/platform"):
                directory = self.directory / target
                directory.mkdir(parents=True)
                (directory / "kustomization.yaml").write_text("resources: []\n")
        self.write_routes("mbk", [route("Local"), route("Shared")])
        self.write_routes(
            "syd", [route("Remote"), route("Shared"), route("Hidden", enabled="false")]
        )

    def write_routes(self, cluster, resources):
        directory = self.directory / f"apps/overlays/{cluster}"
        (directory / "kustomization.yaml").write_text("resources: [routes.yaml]\n")
        (directory / "routes.yaml").write_text(
            "\n---\n".join(json.dumps(r) for r in resources)
        )

    def render(self, **environment):
        return subprocess.run(
            ["sh", str(APP / "render_dashboard.sh"), str(APP), str(self.output)],
            env=os.environ
            | {
                "HOMELAB_DIRECTORY": str(HOMELAB),
                "HOMELAB_INFRASTRUCTURE_FILE": str(
                    ROOT / "tests/fixtures/homepage/infrastructure.json"
                ),
                "HOMEPAGE_CLUSTER": "mbk",
                "HOMEPAGE_GATUS_STATUSES_FILE": str(self.gatus),
                "KUBELAB_DIRECTORY": str(self.directory),
                "KUBECTL": str(self.kubectl),
                "POD_PLACEMENTS": str(self.placements),
                "POD_QUERIES": str(self.queries),
                "REAL_KUBECTL": shutil.which("kubectl"),
                "SYSTEM_KUBECTL": shutil.which("kubectl"),
            }
            | environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def groups(self, tab=None):
        groups = read_yaml(self.output / "services.yaml")
        if tab is not None:
            groups = next(group[tab] for group in groups if tab in group)
            if groups and not isinstance(next(iter(groups[0].values())), list):
                groups = [{tab: groups}]

        def leaves(groups):
            for group in groups:
                for name, cards in group.items():
                    if cards and isinstance(next(iter(cards[0].values())), list):
                        yield from leaves(cards)
                    else:
                        yield name, cards

        return dict(leaves(groups))

    def services(self):
        return {
            name: service
            for entries in self.groups().values()
            for entry in entries
            for name, service in entry.items()
        }
