#!/usr/bin/env python3
"""Discover Updatecli manifests for embedded container pins."""

import argparse
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def image_manifest(path, key, repository, tag, *, versioned=True):
    version, separator, _ = tag.partition("@")
    sources = {}
    if versioned and re.fullmatch(r"v?\d+(?:\.\d+){0,2}", version):
        sources["version"] = {
            "kind": "dockerimage",
            "spec": {
                "image": repository,
                "tagfilter": r"^v?[0-9]+(?:\.[0-9]+){0,2}$",
                "versionfilter": {
                    "kind": "regex/semver",
                    "pattern": "*",
                    "regex": r"^(v?[0-9]+(?:\.[0-9]+){0,2})$",
                },
            },
        }
        version = '{{ source "version" }}'
    else:
        # Preserve source variants and database compatibility; refresh their digest.
        if not separator:
            return None
    sourceid = "version"
    if separator:
        sourceid = "digest"
        sources["digest"] = {
            "kind": "dockerdigest",
            "spec": {"image": repository, "tag": version},
            "transformers": [{"find": r"sha256:[a-f0-9]{64}$"}],
        }
    target = {
        "kind": "yaml",
        "sourceid": sourceid,
        "spec": {"engine": "yamlpath", "file": path, "key": key},
    }
    if separator:
        target["transformers"] = [{"addprefix": version + "@"}]
    return {
        "name": f"Update Docker: {path} {key}",
        "pipelineid": "update-docker-"
        + re.sub(r"[^a-z0-9]+", "-", f"{path}-{key}".lower()).strip("-"),
        "labels": {"group": "docker"},
        "sources": dict(sorted(sources.items())),
        "targets": {"image": target},
    }


def manifests(path, document):
    def walk(value, key):
        if isinstance(value, dict):
            image = value.get("image")
            if isinstance(image, dict) and image.get("repository") and image.get("tag"):
                yield image_manifest(
                    path, key + ".image.tag", image["repository"], str(image["tag"])
                )
            for field, item in value.items():
                child = key + "." + field
                if (
                    document.get("kind") == "Cluster"
                    and field in {"imageName", "reference"}
                    and isinstance(item, str)
                    and "@sha256:" in item
                ):
                    # Split at the tag separator, preserving registry ports.
                    repository, tag = item.split("@", 1)[0].rsplit(":", 1)
                    manifest = image_manifest(
                        path,
                        child,
                        repository,
                        tag + "@" + item.split("@", 1)[1],
                        versioned=False,
                    )
                    if manifest:
                        manifest["targets"]["image"]["transformers"][0]["addprefix"] = (
                            repository + ":" + tag + "@"
                        )
                    yield manifest
                yield from walk(item, child)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                yield from walk(item, f"{key}[{index}]")

    if document.get("kind") in {"Cluster", "HelmRelease"}:
        yield from filter(None, walk(document, "$"))


def discover():
    tracked = subprocess.check_output(
        ["git", "ls-files", "--cached", "--exclude-standard", "--others"],
        cwd=ROOT,
        text=True,
    )
    paths = sorted(
        {
            path
            for path in tracked.splitlines()
            if path.startswith(("apps/", "clusters/", "platform/"))
            and path.endswith(".yaml")
            and (ROOT / path).is_file()
        }
    )
    result = subprocess.check_output(
        # Updatecli can write anchor definitions, but cannot traverse aliases.
        # Clear aliases before JSON encoding loses their node kind; keep list indices.
        [
            "yq",
            "--indent=0",
            "--output-format=json",
            '(.. | select(kind == "alias")) = null | [filename, .]',
            *paths,
        ],
        cwd=ROOT,
        text=True,
    )
    for line in result.splitlines():
        path, document = json.loads(line)
        if isinstance(document, dict):
            yield from manifests(path, document)


def write_manifest(path, manifest):
    # Render YAML so Go template quotes are not escaped by JSON encoding.
    content = subprocess.check_output(
        ["yq", "--input-format=json", "--prettyPrint", "."],
        input=json.dumps(manifest),
        text=True,
    )
    path.write_text(content)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    args.directory.mkdir(exist_ok=True, parents=True)
    for index, manifest in enumerate(discover()):
        write_manifest(args.directory / f"{index:03}.yaml", manifest)


if __name__ == "__main__":
    main()
