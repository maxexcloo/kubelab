"""Small helpers for native manifest fixtures and repository renders."""

import copy
import json
import shutil
import subprocess
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLUSTERS = tuple(path.name for path in sorted((ROOT / "clusters").iterdir()) if path.is_dir())


def read_yaml(path):
    # Resolve merge anchors before tests rewrite YAML documents as JSON.
    return json.loads(subprocess.check_output(
        ["yq", "--yaml-fix-merge-anchor-to-spec", "-o=json", ".", str(path)],
        text=True,
    ))


def read_resources(path):
    documents = subprocess.check_output(
        ["yq", "ea", "-o=json", "[.]", str(path)], text=True
    )
    return [document for document in json.loads(documents) if document]


def render_resources(path):
    rendered = subprocess.check_output(["kubectl", "kustomize", str(path)], text=True)
    documents = subprocess.check_output(
        ["yq", "ea", "-o=json", "[.]"], input=rendered, text=True
    )
    return [document for document in json.loads(documents) if document]


@cache
def _repository_resources(relative):
    return render_resources(ROOT / relative)


def repository_resources(relative):
    # Cache only unchanged repository inputs; callers can mutate their own copy.
    return copy.deepcopy(_repository_resources(relative))


def copy_repository(destination, paths=("apps", "clusters", "platform", "scripts")):
    for relative in paths:
        target = Path(destination) / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(ROOT / relative, target)
