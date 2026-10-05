"""Bootstrap must validate provisioned credentials before writing to Kubernetes."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


class BootstrapSecretTests(unittest.TestCase):
    def test_invalid_token_never_reaches_kubernetes(self):
        cases = [
            ({"fields": []}, 0),
            ({"fields": [{"id": "credential", "value": ""}]}, 0),
            ({"fields": [{"id": "credential", "value": None}]}, 0),
            ({"fields": [{"id": "credential", "value": 123}]}, 0),
            ({"fields": [{"id": "credential", "value": "fixture-token"}]}, 1),
            ({"fields": [{"id": "credential", "value": "fixture-token"}]}, 0),
        ]
        for response, status in cases:
            with self.subTest(response=response, status=status), tempfile.TemporaryDirectory() as directory:
                temporary = Path(directory)
                marker = temporary / "kubectl-called"
                op = temporary / "op"
                op.write_text(
                    '#!/usr/bin/env bash\n'
                    'if [[ "$1" == document ]]; then\n'
                    '  while [[ "$1" != --out-file ]]; do shift; done\n'
                    '  printf "{}" > "$2"\n'
                    'else\n'
                    '  printf "%s" "$TOKEN_RESPONSE"\n'
                    '  exit "$TOKEN_STATUS"\n'
                    'fi\n'
                )
                kubectl = temporary / "kubectl"
                kubectl.write_text('#!/usr/bin/env bash\ntouch "$KUBECTL_MARKER"\ncat >/dev/null\n')
                for executable in [op, kubectl]:
                    executable.chmod(0o755)
                result = subprocess.run(
                    ["bash", ROOT / "scripts/bootstrap_cluster_secrets.sh", "mbk"],
                    capture_output=True, text=True,
                    env=os.environ | {
                        "KUBECTL_MARKER": str(marker),
                        "PATH": f"{temporary}:{os.environ['PATH']}",
                        "TMPDIR": directory,
                        "TOKEN_RESPONSE": json.dumps(response),
                        "TOKEN_STATUS": str(status),
                    },
                )
                valid = status == 0 and response == cases[-1][0]
                self.assertEqual(result.returncode == 0, valid, result.stderr)
                self.assertEqual(marker.exists(), valid)
                self.assertNotIn("fixture-token", result.stdout + result.stderr)
                self.assertEqual(sorted(p.name for p in temporary.iterdir()),
                                 ["kubectl", "kubectl-called", "op"] if valid else ["kubectl", "op"])


if __name__ == "__main__":
    unittest.main()
