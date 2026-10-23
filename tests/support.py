"""Small helpers for native manifest fixtures and repository renders."""

import atexit
import copy
import json
import shutil
import subprocess
import tempfile
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLUSTERS = tuple(
    path.name for path in sorted((ROOT / "clusters").iterdir()) if path.is_dir()
)


def read_yaml(path):
    # Resolve merge anchors before tests rewrite YAML documents as JSON.
    return json.loads(
        subprocess.check_output(
            ["yq", "--yaml-fix-merge-anchor-to-spec", "-o=json", ".", str(path)],
            text=True,
        )
    )


def read_resources(path):
    documents = subprocess.check_output(
        ["yq", "ea", "-o=json", "[.]", str(path)], text=True
    )
    return [document for document in json.loads(documents) if document]


@cache
def _rendered_manifests():
    # Render as Flux builds each path, including its postBuild substitutions.
    directory = Path(tempfile.mkdtemp(prefix="kubelab-render."))
    atexit.register(shutil.rmtree, directory, ignore_errors=True)
    subprocess.run(
        [ROOT / "scripts/render_manifests.sh", directory], check=True, cwd=ROOT
    )
    return directory


@cache
def _repository_resources(relative):
    return read_resources(_rendered_manifests() / f"{relative}.yaml")


def repository_resources(relative):
    # Cache only unchanged repository inputs; callers can mutate their own copy.
    return copy.deepcopy(_repository_resources(relative))
