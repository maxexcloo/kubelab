"""Changing an app hostname must update every native consumer without extra edits."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read_yaml(path):
    return json.loads(subprocess.check_output(["yq", "-o=json", ".", str(path)]))


class AppSettingsTests(unittest.TestCase):
    def test_hostname_changes_reach_all_consumers(self):
        settings_files = sorted((ROOT / "apps/base").glob("*/*settings.yaml"))
        for settings in settings_files:
            resource = read_yaml(settings)
            if not isinstance(resource, dict) or resource.get("kind") != "HelmRelease":
                continue
            routes = resource["spec"]["values"].get("route", {})
            routes = [routes] if "hostnames" in routes else routes.values()
            for route in routes:
                if "hostnames" not in route:
                    continue
                with self.subTest(app=settings.parent.name), tempfile.TemporaryDirectory() as directory:
                    app = Path(directory) / settings.parent.name
                    shutil.copytree(settings.parent, app)
                    old = route["hostnames"][0]
                    route["hostnames"][0] = "renamed.example.test"
                    (app / settings.name).write_text(json.dumps(resource))
                    output = subprocess.check_output(["kustomize", "build", str(app)], text=True)
                    self.assertIn("renamed.example.test", output)
                    self.assertNotIn(old, output)
                    self.assertNotIn("app.invalid", output)


if __name__ == "__main__":
    unittest.main()
