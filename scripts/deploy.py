#!/usr/bin/env python3
"""Reconcile and verify one application at an exact main revision."""

import json
import subprocess
import sys
import time

ROOT_SOURCE = "flux-system"
TIMEOUT = 300


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def ready(resource):
    metadata = resource["metadata"]
    status = resource.get("status", {})
    conditions = {item["type"]: item for item in status.get("conditions", [])}
    condition = conditions.get("Ready", {})
    return (
        condition.get("status") == "True"
        and status.get("observedGeneration") == metadata["generation"]
        and conditions.get("Reconciling", {}).get("status") != "True"
        and conditions.get("Stalled", {}).get("status") != "True"
    )


def deploy(cluster, application, revision=None):
    namespace, _, release = application.partition("/")
    release = release or namespace
    if revision is None:
        revision = run("git", "ls-remote", "origin", "refs/heads/main").split()[0]
    if len(revision) != 40 or any(char not in "0123456789abcdef" for char in revision):
        raise ValueError("revision must be a full Git commit SHA")
    kubectl = ["kubectl", "--context", cluster]
    flux = ["flux", "--context", cluster]
    started = time.monotonic()
    deadline = started + TIMEOUT

    def get(kind, name, namespace):
        return json.loads(run(*kubectl, "get", kind, name, "-n", namespace, "-o", "json"))

    def require_revision():
        source = get("gitrepository", ROOT_SOURCE, "flux-system")
        actual = source.get("status", {}).get("artifact", {}).get("revision", "")
        if actual != f"main@sha1:{revision}":
            raise RuntimeError(f"source revision is {actual}; expected {revision}; rerun for the intended revision")

    subprocess.run([*flux, "reconcile", "source", "git", ROOT_SOURCE], check=True)
    require_revision()
    subprocess.run([*flux, "reconcile", "kustomization", "apps"], check=True)
    applied = get("kustomization", "apps", "flux-system")
    if applied.get("status", {}).get("lastAppliedRevision") != f"main@sha1:{revision}":
        raise RuntimeError("apps has not applied the expected revision")

    while time.monotonic() < deadline:
        helm_release = get("helmrelease", release, namespace)
        if ready(helm_release):
            break
        time.sleep(1)
    else:
        raise TimeoutError(f"{application} did not become Ready at its current generation")

    # Helm's release annotations identify only this release's controllers, including
    # charts whose resource names and instance labels differ from the HelmRelease.
    release_name = helm_release["status"]["history"][0]["name"]
    workloads = json.loads(run(
        *kubectl, "get", "deployments,statefulsets,daemonsets", "-n", namespace, "-o", "json"
    ))["items"]
    owned = [item for item in workloads if item["metadata"].get("annotations", {}).get(
        "meta.helm.sh/release-name"
    ) == release_name]
    if not owned:
        raise RuntimeError(f"no workload controllers found for Helm release {release_name}")
    for workload in owned:
        remaining = max(1, int(deadline - time.monotonic()))
        subprocess.run([
            *kubectl, "rollout", "status", f'{workload["kind"].lower()}/{workload["metadata"]["name"]}',
            "-n", namespace, f"--timeout={remaining}s",
        ], check=True)
    require_revision()
    current = get("helmrelease", release, namespace)
    if current["metadata"]["generation"] != helm_release["metadata"]["generation"] or not ready(current):
        raise RuntimeError("application changed during verification; rerun for the intended revision")
    print(f"{application} Ready at {revision} (verification took {time.monotonic() - started:.1f}s)")


if __name__ == "__main__":
    try:
        deploy(*sys.argv[1:])
    except (IndexError, KeyError, RuntimeError, TimeoutError, ValueError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
