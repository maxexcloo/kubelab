"""Interrupted backups must restore the workload's original operating state."""

import json
import os
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KUBECTL = r"""
import json
import os
import signal
import sys
from pathlib import Path

path = Path(os.environ["BACKUP_TEST_STATE"])
state = json.loads(path.read_text())
args = sys.argv[1:]
# Client flags such as --request-timeout disable in-cluster configuration.
assert not any(arg.startswith("--request-timeout") for arg in args)
mutation = False
if args[0] == "get":
    output = args[-1]
    if "resume-state" in output:
        print(state.get("resume_state", ""), end="")
    elif "replicas" in output:
        print(state["replicas"], end="")
    elif "suspend" in output:
        print(str(state["suspended"]).lower(), end="")
    elif "go-template" in output:
        print("app=test,", end="")
    elif args[1] == "pods":
        print("pod/test", end="")
    else:
        raise AssertionError(args)
elif args[0] == "annotate":
    mutation = True
    if args[-1].endswith("-"):
        state.pop("resume_state", None)
    else:
        if state.get("resume_state"):
            raise AssertionError("Original intent must not be overwritten")
        state["resume_state"] = args[-1].split("=", 1)[1]
elif args[0] == "scale":
    mutation = True
    state["replicas"] = int(args[-1].split("=", 1)[1])
elif args[0] == "patch":
    if state.get("fail_restore") and state.get("mutations", 0) >= 3:
        sys.exit(1)
    mutation = True
    state["suspended"] = json.loads(args[-1])["spec"]["suspend"]
elif args[0] == "wait" and state.get("fail_wait"):
    sys.exit(1)
elif args[0] != "wait":
    raise AssertionError(args)
if mutation:
    state["mutations"] = state.get("mutations", 0) + 1
path.write_text(json.dumps(state))
if mutation and state.get("crash_after") == state["mutations"]:
    os.kill(os.getppid(), signal.SIGKILL)
"""


class BackupRecoveryTests(unittest.TestCase):
    def run_backup(self, directory, state, **environment):
        return subprocess.run(
            ["sh", str(directory / "backup.sh")],
            capture_output=True,
            env=os.environ
            | {
                "BACKUP_BUCKET": "test",
                "BACKUP_ENDPOINT": "https://example.invalid",
                "BACKUP_TEST_STATE": str(state),
                "CLUSTER": "example",
                "DEPLOYMENT": "test",
                "HELM_RELEASE": "test",
                "PATH": f"{directory}:{os.environ['PATH']}",
                "POD_NAMESPACE": "test",
            }
            | environment,
            text=True,
            timeout=15,
            check=False,
        )

    def prepare(self, directory):
        kubectl = directory / "kubectl"
        kubectl.write_text(f"#!{sys.executable}\n" + KUBECTL)
        kubectl.chmod(0o755)
        timeout = directory / "timeout"
        timeout.write_text(
            '#!/bin/sh\ncase "$1" in 180|600) ;; *) exit 2 ;; esac\nshift\nexec "$@"\n'
        )
        timeout.chmod(0o755)
        restic = directory / "restic"
        restic.write_text(
            '#!/bin/sh\nprintf "%s\\n" "$*" >> "$BACKUP_TEST_STATE.restic"\n'
        )
        restic.chmod(0o755)
        (directory / "sources").mkdir()
        (directory / "sources/data.db").write_text("retained application data")
        (directory / "snapshot").mkdir()
        source = (ROOT / "platform/backups/files/backup.sh").read_text()
        source = source.replace("/tools/kubectl", str(kubectl))
        source = source.replace("/hooks/snapshot.sh", str(directory / "hook.sh"))
        source = source.replace("/sources", str(directory / "sources"))
        source = source.replace("/snapshot", str(directory / "snapshot"))
        (directory / "backup.sh").write_text(source)

    def test_sigkill_at_each_state_transition_recovers_on_retry(self):
        # Capture, suspension, scale-down, both restore operations, and intent removal.
        for crash_after in range(1, 7):
            for replicas, suspended in [(2, False), (0, False), (2, True), (0, True)]:
                with (
                    self.subTest(
                        crash_after=crash_after, replicas=replicas, suspended=suspended
                    ),
                    tempfile.TemporaryDirectory() as temporary,
                ):
                    directory = Path(temporary)
                    self.prepare(directory)
                    state = directory / "state.json"
                    state.write_text(
                        json.dumps(
                            {
                                "crash_after": crash_after,
                                "replicas": replicas,
                                "suspended": suspended,
                            }
                        )
                    )
                    interrupted = self.run_backup(directory, state)
                    self.assertEqual(
                        interrupted.returncode, -signal.SIGKILL, interrupted.stderr
                    )
                    interrupted_state = json.loads(state.read_text())
                    if crash_after < 6:
                        self.assertEqual(
                            interrupted_state["resume_state"],
                            f"{replicas}/{str(suspended).lower()}",
                        )
                    if crash_after == 3:
                        self.assertEqual(interrupted_state["replicas"], 0)
                        self.assertTrue(interrupted_state["suspended"])
                    retried = self.run_backup(directory, state)
                    self.assertEqual(retried.returncode, 0, retried.stderr)
                    restored = json.loads(state.read_text())
                    self.assertEqual(restored["replicas"], replicas)
                    self.assertEqual(restored["suspended"], suspended)
                    self.assertNotIn("resume_state", restored)
                    self.assertEqual(
                        (directory / "snapshot/data/data.db").read_text(),
                        "retained application data",
                    )
                    self.assertIn(
                        "backup --host example/test",
                        Path(str(state) + ".restic").read_text(),
                    )

    def test_snapshot_failure_restores_workload_without_uploading(self):
        for phase in ["snapshot", "wait"]:
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                self.prepare(directory)
                state = directory / "state.json"
                state.write_text(
                    json.dumps(
                        {
                            "fail_wait": phase == "wait",
                            "replicas": 2,
                            "suspended": False,
                        }
                    )
                )
                (directory / "hook.sh").write_text(
                    'grep -q \'"replicas": 0\' "$BACKUP_TEST_STATE" || exit 2\n'
                    'touch "$BACKUP_TEST_STATE.quiesced"\nexit 1\n'
                )
                result = self.run_backup(directory, state)
                self.assertEqual(
                    Path(str(state) + ".quiesced").exists(), phase == "snapshot"
                )
                self.assertNotEqual(result.returncode, 0)
                restored = json.loads(state.read_text())
                self.assertEqual(restored["replicas"], 2)
                self.assertFalse(restored["suspended"])
                self.assertNotIn("resume_state", restored)
                self.assertFalse(Path(str(state) + ".restic").exists())

    def test_missing_cluster_fails_before_quiescing_the_workload(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.prepare(directory)
            state = directory / "state.json"
            original = json.dumps({"replicas": 2, "suspended": False})
            state.write_text(original)
            result = self.run_backup(directory, state, CLUSTER="")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("CLUSTER is required", result.stderr)
            self.assertEqual(state.read_text(), original)

    def test_failed_restore_keeps_original_intent_until_a_successful_retry(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.prepare(directory)
            state = directory / "state.json"
            state.write_text(
                json.dumps(
                    {
                        "fail_restore": True,
                        "replicas": 2,
                        "suspended": False,
                    }
                )
            )
            failed = self.run_backup(directory, state)
            self.assertNotEqual(failed.returncode, 0)
            remaining = json.loads(state.read_text())
            self.assertEqual(remaining["resume_state"], "2/false")
            self.assertEqual(remaining["replicas"], 2)
            self.assertTrue(remaining["suspended"])
            self.assertFalse(Path(str(state) + ".restic").exists())
            remaining.pop("fail_restore")
            state.write_text(json.dumps(remaining))
            retried = self.run_backup(directory, state)
            self.assertEqual(retried.returncode, 0, retried.stderr)
            restored = json.loads(state.read_text())
            self.assertEqual(restored["replicas"], 2)
            self.assertFalse(restored["suspended"])
            self.assertNotIn("resume_state", restored)


if __name__ == "__main__":
    unittest.main()
