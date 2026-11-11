"""Exercise enrolment decisions with GitHub and GARM response shapes."""

import copy
import importlib.util
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "garm_enrol", ROOT / "apps/base/garm/enrol.py"
)
enrol = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(enrol)
FIXTURES = ROOT / "tests/fixtures/garm"


def fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


class GarmFixture:
    def __init__(self):
        self.repos = []
        self.pools = {}
        self.hooks = {}
        self.writes = []

    def __call__(self, method, path, data=None):
        if method != "GET":
            self.writes.append((method, path, data))
        if path == "/repositories":
            if method == "GET":
                return copy.deepcopy(self.repos)
            repo = {
                "id": str(len(self.repos) + 1),
                "owner": data["owner"],
                "name": data["name"],
                "credentials": {"name": data["credentials_name"]},
            }
            self.repos.append(repo)
            self.pools[repo["id"]] = []
            return copy.deepcopy(repo)
        parts = path.split("/")
        repo_id = parts[2]
        if parts[3] == "webhook":
            if method == "GET":
                if repo_id not in self.hooks:
                    raise urllib.error.HTTPError(path, 404, "not found", {}, None)
                return self.hooks[repo_id]
            self.hooks[repo_id] = {"active": True, "events": ["workflow_job"]}
            return self.hooks[repo_id]
        if method == "GET":
            return copy.deepcopy(self.pools[repo_id])
        pool = dict(data)
        pool["tags"] = [{"name": name} for name in data["tags"]]
        # Exercise GARM's omitempty on zero/false values.
        pool = {key: value for key, value in pool.items() if value}
        if method == "POST":
            pool["id"] = f"pool-{repo_id}"
            self.pools[repo_id].append(pool)
        else:
            previous = self.pools[repo_id][0]
            previous.update(pool)
            if not data["enabled"]:
                previous.pop("enabled", None)
        return copy.deepcopy(pool)


class GarmEnrolmentTests(unittest.TestCase):
    def test_owned_active_repos_include_owned_forks(self):
        github = Mock(return_value=fixture("repositories"))
        self.assertEqual(
            set(enrol.discover(github, fixture("installation"))),
            {"active", "owned-fork"},
        )

    def test_pagination_failure_never_reaches_mutations(self):
        first = fixture("repositories")
        first["repositories"] = [first["repositories"][0]] * 100
        first["total_count"] = 101
        github = Mock(side_effect=[first, urllib.error.URLError("unavailable")])
        garm = Mock()
        with self.assertRaises(urllib.error.URLError):
            enrol.reconcile(garm, enrol.discover(github, fixture("installation")))
        garm.assert_not_called()

    def test_pagination_and_installation_scope(self):
        first = fixture("repositories")
        first["repositories"] = [
            {**first["repositories"][0], "id": number} for number in range(100)
        ]
        first["total_count"] = 101
        last = {
            "total_count": 101,
            "repositories": [{**first["repositories"][0], "id": 100, "name": "new"}],
        }
        github = Mock(side_effect=[first, last])
        self.assertIn("new", enrol.discover(github, fixture("installation")))
        self.assertIn("page=2", github.call_args.args[1])
        for key, value in [
            ("repository_selection", "selected"),
            ("suspended_at", "today"),
        ]:
            installation = fixture("installation")
            installation[key] = value
            with self.assertRaises(ValueError):
                enrol.discover(Mock(), installation)
        with self.assertRaises(ValueError):
            enrol.discover(
                Mock(return_value={"total_count": 1, "repositories": []}),
                fixture("installation"),
            )

    def test_repeated_enrolment_discovery_and_archival_are_idempotent(self):
        garm = GarmFixture()
        active = {"active": {"name": "active"}}
        enrol.reconcile(garm, active)
        self.assertEqual(
            [method for method, _, _ in garm.writes], ["POST", "POST", "POST"]
        )
        garm.writes.clear()
        enrol.reconcile(garm, active)
        self.assertEqual(garm.writes, [])
        active["new"] = {"name": "new"}
        enrol.reconcile(garm, active)
        self.assertEqual(len(garm.repos), 2)
        garm.writes.clear()
        enrol.reconcile(garm, {"new": {"name": "new"}})
        self.assertEqual(len(garm.writes), 1)
        self.assertEqual(garm.writes[0][0], "PUT")
        self.assertFalse(garm.writes[0][2]["enabled"])
        self.assertEqual(len(garm.repos), 2)
        garm.writes.clear()
        enrol.reconcile(garm, {"new": {"name": "new"}})
        self.assertEqual(garm.writes, [])
        enrol.reconcile(garm, active)
        self.assertTrue(garm.writes[0][2]["enabled"])

    def test_released_api_response_needs_no_updates(self):
        response = fixture("garm")
        garm = GarmFixture()
        repo_id = response["repository"]["id"]
        garm.repos = [response["repository"]]
        garm.pools[repo_id] = [response["pool"]]
        garm.hooks[repo_id] = response["hook"]
        enrol.reconcile(garm, {"active": {"name": "active"}})
        self.assertEqual(garm.writes, [])

    def test_bootstrap_uses_supported_login_controller_and_app_requests(self):
        github = Mock(
            side_effect=[
                fixture("installation"),
                {"token": "fixture-installation-token"},
                fixture("repositories"),
            ]
        )
        garm = Mock(side_effect=[{"token": "fixture-login-token"}, {}, {}, [], {}])
        with tempfile.TemporaryDirectory() as directory:
            secret = Path(directory)
            for name, value in {
                "app-id": "123",
                "installation-id": "456",
                "app-private-key": "fixture-key",
                "username": "fixture-user",
                "password": "fixture-password",
            }.items():
                (secret / name).write_text(value)
            with (
                patch.object(enrol, "Path", return_value=secret),
                patch.object(enrol, "app_jwt", return_value="fixture-app-jwt"),
                patch.object(enrol, "API", side_effect=[github, garm]),
                patch.object(enrol, "reconcile") as reconcile,
                patch.dict(
                    enrol.os.environ,
                    {
                        "GARM_API_URL": "http://garm.invalid/api/v1",
                        "GARM_PUBLIC_URL": "https://garm.invalid",
                    },
                ),
            ):
                enrol.main()
        self.assertEqual(garm.call_args_list[0].args[:2], ("POST", "/auth/login"))
        controller = garm.call_args_list[2].args
        self.assertEqual(controller[:2], ("PUT", "/controller"))
        self.assertEqual(
            controller[2]["metadata_url"], "https://garm.invalid/api/v1/metadata"
        )
        credential = garm.call_args_list[4].args
        self.assertEqual(credential[:2], ("POST", "/github/credentials"))
        self.assertEqual(credential[2]["app"]["private_key_bytes"], "Zml4dHVyZS1rZXk=")
        self.assertEqual(credential[2]["auth_type"], "app")
        self.assertEqual(set(reconcile.call_args.args[1]), {"active", "owned-fork"})

    def test_transient_webhook_error_never_creates_a_pool(self):
        garm = GarmFixture()
        enrol.reconcile(garm, {"active": {"name": "active"}})
        garm.writes.clear()

        def failing(method, path, data=None):
            if path.endswith("/webhook"):
                raise urllib.error.HTTPError(path, 503, "unavailable", {}, None)
            return garm(method, path, data)

        with self.assertRaises(urllib.error.HTTPError) as caught:
            enrol.reconcile(failing, {"active": {"name": "active"}})
        caught.exception.close()
        self.assertEqual(garm.writes, [])

    def test_foreign_credentials_and_unmanaged_pools_are_preserved(self):
        garm = GarmFixture()
        enrol.reconcile(garm, {"active": {"name": "active"}})
        garm.pools["1"][0]["provider_name"] = "other"
        garm.writes.clear()
        enrol.reconcile(garm, {})
        self.assertEqual(garm.writes, [])
        garm.repos[0]["credentials"]["name"] = "other"
        with self.assertRaises(ValueError):
            enrol.reconcile(garm, {"active": {"name": "active"}})
        self.assertEqual(garm.writes, [])


if __name__ == "__main__":
    unittest.main()
