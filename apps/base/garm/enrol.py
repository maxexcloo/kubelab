"""Enrol owned, active repositories through GARM's supported REST API."""

import base64
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

OWNER = "maxexcloo"
CREDENTIAL = "maxexcloo-app"
PROVIDER = "mercury"
LABEL = "mercury-incus"


class API:
    def __init__(self, base, token=""):
        self.base = base
        self.token = token

    def __call__(self, method, path, data=None):
        headers = {"Accept": "application/json", "User-Agent": "kubelab-garm-enrol"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        body = None
        if data is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(data).encode()
        request = urllib.request.Request(
            self.base + path, data=body, headers=headers, method=method
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            content = response.read()
            return json.loads(content) if content else None


def app_jwt(app_id, key_path):
    def encode(value):
        return base64.urlsafe_b64encode(value).rstrip(b"=")

    now = int(time.time())
    message = b".".join(
        encode(json.dumps(value).encode())
        for value in [
            {"alg": "RS256", "typ": "JWT"},
            {"iat": now - 60, "exp": now + 540, "iss": app_id},
        ]
    )
    signature = subprocess.run(
        ["openssl", "dgst", "-sha256", "-sign", str(key_path)],
        input=message,
        capture_output=True,
        check=True,
    ).stdout
    return (message + b"." + encode(signature)).decode()


def discover(github, installation):
    """Finish every page before allowing GARM mutations."""
    if (
        installation["account"]["login"].lower() != OWNER
        or installation["account"]["type"] != "User"
        or installation["repository_selection"] != "all"
        or installation["suspended_at"] is not None
    ):
        raise ValueError("GitHub App must be active on all maxexcloo repositories")
    repositories = []
    page = 1
    while True:
        result = github("GET", f"/installation/repositories?per_page=100&page={page}")
        repositories.extend(result["repositories"])
        if len(result["repositories"]) < 100:
            break
        page += 1
    if (
        len(repositories) != result["total_count"]
        or len({repo["id"] for repo in repositories}) != result["total_count"]
    ):
        raise ValueError("GitHub repository inventory changed; retry next run")
    return {
        repo["name"].lower(): repo
        for repo in repositories
        if repo["owner"]["login"].lower() == OWNER
        and repo["owner"]["type"] == "User"
        and not repo["archived"]
        and not repo["disabled"]
    }


def managed(pool):
    return pool["provider_name"] == PROVIDER and any(
        tag["name"] == LABEL for tag in pool.get("tags", [])
    )


def pool_settings(enabled):
    return {
        "enabled": enabled,
        "flavor": "garm-vm",
        "image": "images:ubuntu/24.04/cloud",
        "max_runners": 1,
        "min_idle_runners": 0,
        "os_arch": "amd64",
        "os_type": "linux",
        "runner_bootstrap_timeout": 20,
        # Match only explicit opt-in jobs, leaving existing generic labels alone.
        "tags": [LABEL],
        "enable_shell": False,
    }


def reconcile(garm, active):
    repositories = garm("GET", "/repositories")
    owned = {
        repo["name"].lower(): repo
        for repo in repositories
        if repo["owner"].lower() == OWNER and repo["credentials"]["name"] == CREDENTIAL
    }
    for name, github_repo in sorted(active.items()):
        if name not in owned:
            # A separately managed entity is never silently adopted.
            if any(
                repo["owner"].lower() == OWNER and repo["name"].lower() == name
                for repo in repositories
            ):
                raise ValueError(f"repository already uses other credentials: {name}")
            owned[name] = garm(
                "POST",
                "/repositories",
                {
                    "owner": OWNER,
                    "name": github_repo["name"],
                    "credentials_name": CREDENTIAL,
                    "webhook_secret": secrets.token_urlsafe(48),
                    "forge_type": "github",
                },
            )
    for name, repo in sorted(owned.items()):
        path = f"/repositories/{repo['id']}"
        pools = garm("GET", path + "/pools")
        ours = [pool for pool in pools if managed(pool)]
        if len(ours) > 1:
            raise ValueError(f"multiple managed pools for {name}")
        enabled = name in active
        if enabled:
            try:
                hook = garm("GET", path + "/webhook")
            except urllib.error.HTTPError as error:
                if error.code != 404:
                    raise
                error.close()
                hook = None
            if hook and (
                not hook.get("active", False)
                or hook.get("insecure_ssl", False)
                or hook["events"] != ["workflow_job"]
            ):
                garm("DELETE", path + "/webhook")
                hook = None
            if not hook:
                garm("POST", path + "/webhook", {"insecure_ssl": False})
        settings = pool_settings(enabled)
        if ours:
            pool = ours[0]
            # GARM omits zero and false fields in its JSON responses.
            current = {
                key: pool.get(key, type(value)()) for key, value in settings.items()
            }
            current["tags"] = [tag["name"] for tag in pool.get("tags", [])]
            if current != settings:
                garm("PUT", path + f"/pools/{pool['id']}", settings)
        elif enabled:
            garm("POST", path + "/pools", {"provider_name": PROVIDER, **settings})
    print(f"Reconciled {len(active)} active owned repositories")


def main():
    secret = Path("/secrets")
    app_id = int((secret / "app-id").read_text())
    installation_id = int((secret / "installation-id").read_text())
    github = API("https://api.github.com", app_jwt(app_id, secret / "app-private-key"))
    installation = github("GET", f"/app/installations/{installation_id}")
    token = github("POST", f"/app/installations/{installation_id}/access_tokens", {})
    github.token = token["token"]
    active = discover(github, installation)
    garm = API(os.environ["GARM_API_URL"])
    garm.token = garm(
        "POST",
        "/auth/login",
        {
            "username": (secret / "username").read_text().strip(),
            "password": (secret / "password").read_text(),
        },
    )["token"]
    public = os.environ["GARM_PUBLIC_URL"]
    desired = {
        "callback_url": public + "/api/v1/callbacks",
        "metadata_url": public + "/api/v1/metadata",
        "webhook_url": public + "/webhooks",
    }
    controller = garm("GET", "/controller")
    if any(controller.get(key) != value for key, value in desired.items()):
        garm("PUT", "/controller", desired)
    credentials = garm("GET", "/github/credentials")
    if not any(credential["name"] == CREDENTIAL for credential in credentials):
        garm(
            "POST",
            "/github/credentials",
            {
                "name": CREDENTIAL,
                "endpoint": "github.com",
                "auth_type": "app",
                "app": {
                    "app_id": app_id,
                    "installation_id": installation_id,
                    "private_key_bytes": base64.b64encode(
                        (secret / "app-private-key").read_bytes()
                    ).decode(),
                },
            },
        )
    reconcile(garm, active)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        # API response bodies and request payloads can contain credentials.
        print(
            f"Enrolment failed ({type(error).__name__}); retry next run",
            file=sys.stderr,
        )
        sys.exit(1)
