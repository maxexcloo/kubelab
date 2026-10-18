#!/usr/bin/env python3
"""Discover Updatecli manifests for embedded container pins."""

import argparse
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def image_manifest(path, key, repository, tag, *, major=False):
    # Keep each tag's shape, such as a "v" prefix or "-alpine" variant suffix;
    # updates replace any legacy digest with the exact tag.
    match = re.fullmatch(
        r"(v?)(\d+)((?:\.\d+){0,2})(-[A-Za-z0-9.-]+)?", tag.partition("@")[0]
    )
    if not match:
        return None
    prefix, current_major, minor, suffix = match.groups()
    components = r"(?:\.[0-9]+)" * minor.count(".")
    # Database images stay on their major version for data compatibility.
    version = re.escape(current_major) if major else "[0-9]+"
    pattern = (
        "^" + prefix + "(" + version + components + ")" + re.escape(suffix or "") + "$"
    )
    return {
        "name": f"Update Docker: {path} {key}",
        "pipelineid": "update-docker-"
        + re.sub(r"[^a-z0-9]+", "-", f"{path}-{key}".lower()).strip("-"),
        "labels": {"group": "docker"},
        "sources": {
            "version": {
                "kind": "dockerimage",
                "spec": {
                    "image": repository,
                    "tagfilter": pattern,
                    "versionfilter": {
                        "kind": "regex/semver",
                        "pattern": "*",
                        "regex": pattern,
                    },
                },
            }
        },
        "targets": {
            "image": {
                "kind": "yaml",
                "sourceid": "version",
                "spec": {"engine": "yamlpath", "file": path, "key": key},
            }
        },
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
                ):
                    # Split at the tag separator, preserving registry ports.
                    repository, tag = item.partition("@")[0].rsplit(":", 1)
                    manifest = image_manifest(path, child, repository, tag, major=True)
                    if manifest:
                        manifest["targets"]["image"]["transformers"] = [
                            {"addprefix": repository + ":"}
                        ]
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
