"""Shared fixtures for Homepage dashboard integration tests."""

import json
import os
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
            "widget.password": "{{HOMEPAGE_VAR_BESZEL_PASSWORD}}",
            "widget.type": "beszel",
            "widget.url": "https://beszel.example.net",
            "widget.username": "{{HOMEPAGE_VAR_BESZEL_USERNAME}}",
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
        self.published = self.directory / "published"
        self.remote = self.directory / "remote"
        self.remote.mkdir()
        bin_directory = self.directory / "bin"
        bin_directory.mkdir()
        self.path = f"{bin_directory}{os.pathsep}{os.environ['PATH']}"
        wget = bin_directory / "wget"
        wget.write_text("""#!/usr/bin/env python3
import os
import shutil
import sys
from urllib.parse import urlparse
url = urlparse(sys.argv[-1])
source = os.path.join(os.environ["REMOTE_ROUTES"], url.hostname + url.path.replace("/", "_"))
if not os.path.exists(source):
    sys.exit(4)
shutil.copy(source, sys.argv[sys.argv.index("-O") + 1])
""")
        wget.chmod(0o755)
        self.placements = self.directory / "placements.json"
        self.placements.write_text("{}")
        self.queries = self.directory / "queries.jsonl"
        self.routes = self.directory / "routes.json"
        self.kubectl = self.directory / "kubectl"
        self.kubectl.write_text("""#!/usr/bin/env python3
import json
import os
import sys
if sys.argv[1:3] == ["get", "httproutes"]:
    with open(os.environ["HTTP_ROUTES"]) as source:
        print(source.read())
elif sys.argv[1:2] == ["--namespace"] and sys.argv[3:5] == ["get", "pods"]:
    with open(os.environ["POD_QUERIES"], "a") as output:
        output.write(json.dumps(sys.argv[1:]) + "\\n")
    with open(os.environ["POD_PLACEMENTS"]) as source:
        placements = json.load(source)
        nodes = placements.get(sys.argv[2] + "/" + sys.argv[-1], placements.get(sys.argv[2], ["node"]))
    if nodes == "fail":
        sys.exit(1)
    print("\\n".join(nodes))
else:
    sys.exit(f"Unexpected kubectl call: {sys.argv[1:]}")
""")
        self.kubectl.chmod(0o755)
        self.write_routes(
            [route("Local"), route("Shared"), route("Hidden", enabled="false")]
        )

    def write_routes(self, routes):
        self.routes.write_text(json.dumps({"items": routes}))

    def serve_remote_routes(self, cluster, routes):
        name = f"homepage.{cluster}.excloo.dev_dashboard_routes.json"
        (self.remote / name).write_text(routes)

    def render(self, **environment):
        return subprocess.run(
            [
                "sh",
                str(APP / "render_dashboard.sh"),
                str(APP),
                str(self.output),
                str(self.published),
            ],
            env=os.environ
            | {
                "HOMELAB_DIRECTORY": str(HOMELAB),
                "HOMELAB_INFRASTRUCTURE_FILE": str(
                    ROOT / "tests/fixtures/homepage/infrastructure.json"
                ),
                "HOMEPAGE_CLUSTER": "mbk",
                "HTTP_ROUTES": str(self.routes),
                "KUBECTL": str(self.kubectl),
                "PATH": self.path,
                "POD_PLACEMENTS": str(self.placements),
                "POD_QUERIES": str(self.queries),
                "REMOTE_ROUTES": str(self.remote),
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
