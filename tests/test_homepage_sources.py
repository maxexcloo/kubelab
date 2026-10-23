"""Check Homepage dashboard sources without network access."""

import json
import os
import tarfile
import unittest

from homepage_support import HomepageDashboardFixture, route
from support import read_yaml


class HomepageSourcesTests(HomepageDashboardFixture, unittest.TestCase):
    def test_applied_revision_cache_and_failed_download_preserve_configuration(self):
        revision_file = self.directory / "revision"
        downloads = self.directory / "downloads"
        archive = self.directory / "snapshot.tar.gz"
        cache = self.directory / "cache"
        commands = self.directory / "commands"
        commands.mkdir()
        kubectl = commands / "kubectl"
        kubectl.write_text("""#!/bin/sh
if [ "$3" = get ] && [ "$4" = kustomization ]; then
  cat "$REVISION_FIXTURE"
elif [ "$3" = get ] && [ "$4" = gitrepository ] && [ "$5" = flux-system ]; then
  printf 'https://github.com/example/kubelab.git'
else
  exec "$REAL_KUBECTL" "$@"
fi
""")
        wget = commands / "wget"
        wget.write_text("""#!/bin/sh
printf '%s\n' "$6" >> "$DOWNLOAD_FIXTURE"
[ "${FAIL_DOWNLOAD:-false}" != true ] || exit 1
cp "$ARCHIVE_FIXTURE" "$2"
""")
        for command in (kubectl, wget):
            command.chmod(0o755)
        environment = {
            "ARCHIVE_FIXTURE": str(archive),
            "DOWNLOAD_FIXTURE": str(downloads),
            "HOMEPAGE_CACHE_DIRECTORY": str(cache),
            "KUBECTL": str(kubectl),
            "KUBELAB_DIRECTORY": "",
            "PATH": str(commands) + os.pathsep + os.environ["PATH"],
            "REAL_KUBECTL": str(self.kubectl),
            "REVISION_FIXTURE": str(revision_file),
        }

        def snapshot():
            with tarfile.open(archive, "w:gz") as output:
                for directory in ("apps", "clusters"):
                    output.add(
                        self.directory / directory, arcname="snapshot/" + directory
                    )

        first = "a" * 40
        second = "b" * 40
        revision_file.write_text("main@sha1:" + first)
        snapshot()
        result = self.render(**environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Local", self.services())
        self.assertEqual(
            downloads.read_text().splitlines(),
            [
                "https://codeload.github.com/example/kubelab/tar.gz/" + first,
            ],
        )
        self.write_routes("mbk", [route("Future")])
        snapshot()
        result = self.render(**environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Local", self.services())
        self.assertNotIn("Future", self.services())
        self.assertEqual(len(downloads.read_text().splitlines()), 1)
        revision_file.write_text("main@sha1:" + second)
        result = self.render(**environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Future", self.services())
        self.assertNotIn("Local", self.services())
        self.assertEqual(
            downloads.read_text().splitlines()[-1],
            "https://codeload.github.com/example/kubelab/tar.gz/" + second,
        )
        before = {p.name: p.read_bytes() for p in self.output.iterdir()}
        revision_file.write_text("main@sha1:" + "c" * 40)
        self.assertNotEqual(
            self.render(**(environment | {"FAIL_DOWNLOAD": "true"})).returncode, 0
        )
        self.assertEqual((cache / "revision").read_text().strip(), second)
        self.assertEqual(
            before, {p.name: p.read_bytes() for p in self.output.iterdir()}
        )
        revision_file.write_text("main@sha1:invalid")
        self.assertNotEqual(self.render(**environment).returncode, 0)
        self.assertEqual(len(downloads.read_text().splitlines()), 3)
        self.assertEqual(
            before, {p.name: p.read_bytes() for p in self.output.iterdir()}
        )

    def test_minilab_follow_cluster_selection_and_homepage_annotations(self):
        minilab = self.directory / "minilab"
        for cluster, name in (("mbk", "Budget"), ("syd", "Feeds")):
            directory = minilab / "clusters" / cluster
            directory.mkdir(parents=True)
            (directory / "kustomization.yaml").write_text("resources: [app.yaml]\n")
            # Flux substitutes the domain; the dashboard must render it too.
            app = route(
                f"Minilab: {name}", href=f"https://{name.lower()}.${{MINILAB_DOMAIN}}"
            )
            app["metadata"].update({"name": name.lower(), "namespace": name.lower()})
            (directory / "app.yaml").write_text(json.dumps(app))
            source = {
                "apiVersion": "source.toolkit.fluxcd.io/v1",
                "kind": "GitRepository",
                "metadata": {"name": "minilab", "namespace": "flux-system"},
                "spec": {
                    "url": "https://github.com/example/minilab.git",
                    "ref": {"branch": "deploy"},
                },
            }
            selection = {
                "apiVersion": "kustomize.toolkit.fluxcd.io/v1",
                "kind": "Kustomization",
                "metadata": {"name": "minilab", "namespace": "flux-system"},
                "spec": {
                    "path": "./clusters/${cluster_name}",
                    "postBuild": {
                        "substitute": {"MINILAB_DOMAIN": "mini.${public_domain}"}
                    },
                },
            }
            self.write_routes(cluster, [route("Existing"), selection, source])
        result = self.render(MINILAB_DIRECTORY=str(minilab))
        self.assertEqual(result.returncode, 0, result.stderr)
        services = self.services()
        self.assertIn("Budget", services)
        self.assertIn("Feeds", services)
        self.assertIn("Existing", services)
        self.assertEqual(services["Feeds"]["href"], "https://feeds.mini.example.net")
        groups = self.groups()
        self.assertEqual(
            [next(iter(card)) for card in groups["Mini"]], ["Budget", "Feeds"]
        )
        # Only the Home group states the source; cluster groups keep the prefix.
        self.assertIn(
            "Minilab: Feeds",
            [next(iter(card)) for card in self.groups("Clusters")["syd"]],
        )
        self.assertNotIn("Feeds", [next(iter(card)) for card in groups["Applications"]])
        self.assertEqual(
            read_yaml(self.output / "settings.yaml")["layout"]["Home"]["tab"], "Home"
        )
        # Newly deployed apps appear on refresh; removed apps disappear without
        # maintaining a second list of dashboard cards.
        path = minilab / "clusters/syd/app.yaml"
        path.write_text(json.dumps(route("New Tool")))
        self.assertEqual(self.render(MINILAB_DIRECTORY=str(minilab)).returncode, 0)
        self.assertIn("New Tool", self.services())
        self.assertNotIn("Feeds", self.services())
        # Like Flux's strict substitution, a missing variable fails the refresh.
        before = (self.output / "services.yaml").read_bytes()
        path.write_text(json.dumps(route("Unset", href="https://unset.${UNSET}")))
        result = self.render(MINILAB_DIRECTORY=str(minilab))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("UNSET", result.stderr)
        self.assertEqual((self.output / "services.yaml").read_bytes(), before)
        path.write_text(json.dumps(route("New Tool")))
        before = (self.output / "services.yaml").read_bytes()
        (minilab / "clusters/syd/app.yaml").unlink()
        self.assertNotEqual(self.render(MINILAB_DIRECTORY=str(minilab)).returncode, 0)
        self.assertEqual((self.output / "services.yaml").read_bytes(), before)

    def test_required_inputs_fail_without_publishing(self):
        for name in ("FLUX", "HOMELAB_INFRASTRUCTURE_FILE", "KUBECTL"):
            with self.subTest(name=name):
                result = self.render(**{name: ""})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f"{name} is required", result.stderr)
                self.assertFalse(self.output.exists())

    def test_unchanged_refresh_and_invalid_input_preserve_files(self):
        result = self.render()
        self.assertEqual(result.returncode, 0, result.stderr)
        before = {
            p.name: (p.read_bytes(), p.stat().st_mtime_ns)
            for p in self.output.iterdir()
        }
        result = self.render()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            before,
            {
                p.name: (p.read_bytes(), p.stat().st_mtime_ns)
                for p in self.output.iterdir()
            },
        )
        (self.directory / "apps/overlays/syd/routes.yaml").write_text("[broken yaml\n")
        self.assertNotEqual(self.render().returncode, 0)
        self.assertEqual(
            before,
            {
                p.name: (p.read_bytes(), p.stat().st_mtime_ns)
                for p in self.output.iterdir()
            },
        )


if __name__ == "__main__":
    unittest.main()
