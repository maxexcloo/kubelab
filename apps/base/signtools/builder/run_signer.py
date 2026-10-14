"""Mask downloaded credentials before the upstream signer can log an error."""

from pathlib import Path


def prepare_source(source):
    original = """def read_file(file_path: StrPath):
    with open(file_path) as f:
        return f.read()
"""
    replacement = """def read_file(file_path: StrPath):
    with open(file_path) as f:
        value = f.read()
    if Path(file_path).name in {"account_pass.txt", "cert_pass.txt"} and value:
        escaped = value.replace("%", "%25").replace("\\r", "%0D").replace("\\n", "%0A")
        print("::add-mask::" + escaped, flush=True)
    return value
"""
    if source.count(original) != 1:
        raise RuntimeError("Upstream credential reader changed; review the masking patch")
    return source.replace(original, replacement)


if __name__ == "__main__":
    signer = Path("sign.py")
    source = prepare_source(signer.read_text())
    exec(compile(source, str(signer), "exec"), {"__file__": str(signer), "__name__": "__main__"})
