"""Keep signing passwords out of GitHub error logs."""

import ast
import contextlib
import io
import runpy
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PREPARE = runpy.run_path(ROOT / "apps/base/signtools/builder/run_signer.py")["prepare_source"]
READER = """def read_file(file_path: StrPath):
    with open(file_path) as f:
        return f.read()
"""


class SignToolsBuilderTests(unittest.TestCase):
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
