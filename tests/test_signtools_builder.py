"""Keep signing passwords out of GitHub error logs."""

import ast
import contextlib
import io
import runpy
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
PREPARE = runpy.run_path(ROOT / "apps/base/signtools/builder/run_signer.py")["prepare_source"]
CHECK_CONNECTION = runpy.run_path(ROOT / "apps/base/signtools/builder/check_connection.py")["check_connection"]
READER = """def read_file(file_path: StrPath):
    with open(file_path) as f:
        return f.read()
"""


class SignToolsBuilderTests(unittest.TestCase):
    def test_private_https_connection_requires_ui_authentication(self):
        for host in ("10.4.0.2", "100.64.0.2", "fd7a:115c:a1e0::2"):
            with self.subTest(host=host), patch("socket.getaddrinfo", return_value=[(0, 0, 0, "", (host, 443))]), patch(
                "urllib.request.urlopen",
                side_effect=urllib.error.HTTPError("https://signer.test", 401, "Unauthorised", {}, None),
            ):
                CHECK_CONNECTION("https://signer.test")

    def test_public_dns_results_prevent_requests(self):
        addresses = [(0, 0, 0, "", (host, 443)) for host in ("10.4.0.2", "8.8.8.8")]
        with patch("socket.getaddrinfo", return_value=addresses), patch("urllib.request.urlopen") as request:
            with self.assertRaises(RuntimeError):
                CHECK_CONNECTION("https://signer.test")
            request.assert_not_called()

    def test_unprotected_ui_is_rejected(self):
        with patch("socket.getaddrinfo", return_value=[(0, 0, 0, "", ("10.4.0.2", 443))]), patch(
            "urllib.request.urlopen", return_value=MagicMock()
        ), self.assertRaises(RuntimeError):
            CHECK_CONNECTION("https://signer.test")

    def test_http_url_is_rejected_before_connecting(self):
        with patch("socket.getaddrinfo") as resolve, self.assertRaises(RuntimeError):
            CHECK_CONNECTION("http://signer.test")
        resolve.assert_not_called()

    def test_passwords_are_masked_before_returning_to_signer(self):
        namespace = {"Path": Path, "StrPath": str}
        exec(compile(ast.parse(PREPARE(READER)), "sign.py", "exec"), namespace)
        with tempfile.TemporaryDirectory() as directory:
            for name in ("account_pass.txt", "cert_pass.txt", "args.txt"):
                with self.subTest(name=name):
                    path = Path(directory) / name
                    path.write_text("fixture%password\nsecond line")
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output):
                        result = namespace["read_file"](path)
                    self.assertEqual(result, "fixture%password\nsecond line")
                    expected = (
                        "::add-mask::fixture%25password%0Asecond line\n"
                        if name != "args.txt" else ""
                    )
                    self.assertEqual(output.getvalue(), expected)

    def test_upstream_reader_changes_require_review(self):
        for source in ("def read_file(path): pass", READER + READER):
            with self.subTest(source=source), self.assertRaises(RuntimeError):
                PREPARE(source)


if __name__ == "__main__":
    unittest.main()
