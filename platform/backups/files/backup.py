"""Publish file snapshots with online SQLite backups; never prune older snapshots.

Each database snapshot is consistent. A changing file tree is not an atomic app
snapshot; quiesce writes for cutovers that must coordinate files and databases.
"""

import hashlib
import json
import os
from contextlib import closing
from pathlib import Path
import shutil
import sqlite3
import stat
import sys
import tempfile
import time
from datetime import datetime, timezone


SQLITE_HEADER = b"SQLite format 3\x00"


def validate_links(links):
    for relative, target in links.items():
        if relative in {"", "."} or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ValueError("Invalid symbolic link path")
        if not target or Path(target).is_absolute():
            raise ValueError("Absolute symbolic links are not supported")
        pending = list(Path(relative).parent.parts) + list(Path(target).parts)
        resolved = []
        followed = 0
        while pending:
            part = pending.pop(0)
            if part in {"", "."}:
                continue
            if part == "..":
                if not resolved:
                    raise ValueError("Symbolic link escapes the source")
                resolved.pop()
                continue
            resolved.append(part)
            name = "/".join(resolved)
            if name in links:
                followed += 1
                if followed > 40:
                    raise ValueError("Symbolic link cycle or excessive chain")
                if Path(links[name]).is_absolute():
                    raise ValueError("Absolute symbolic links are not supported")
                resolved.pop()
                pending = list(Path(links[name]).parts) + pending


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def reusable(previous, records, relative, checksum):
    try:
        return (
            previous is not None
            and records.get(relative, {}).get("sha256") == checksum
            and digest(previous / "data" / relative) == checksum
        )
    except (AttributeError, OSError):
        return False


def inventory(source, directories=None, links=None):
    result = {}

    def fail(error):
        raise error

    # Path.rglob suppresses scan errors, which could publish an incomplete backup.
    for directory, names, filenames in os.walk(source, onerror=fail, followlinks=False):
        for name in sorted(names + filenames):
            path = Path(directory) / name
            info = path.lstat()
            relative = str(path.relative_to(source))
            if stat.S_ISLNK(info.st_mode):
                if links is None:
                    raise ValueError("Unexpected symbolic link in backup data")
                links[relative] = os.readlink(path)
                continue
            if stat.S_ISDIR(info.st_mode):
                if directories is not None:
                    directories[relative] = stat.S_IMODE(info.st_mode) & 0o777
                continue
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("Special files require an explicit application backup policy")
            result[relative] = path
    if links is not None:
        validate_links(links)
    return result


def restore(backup, target):
    os.umask(0o077)
    backup = Path(backup).resolve(strict=True)
    target = Path(target)
    if backup.name.startswith(".") or not (backup / "manifest.json").is_file():
        raise ValueError("Restore requires a completed backup")
    if target.is_symlink() or (target.exists() and any(target.iterdir())):
        raise ValueError("Restore requires an empty target directory")
    target = target.resolve()
    if target == backup or backup in target.parents:
        raise ValueError("Restore target must be outside the completed backup")
    manifest = json.loads((backup / "manifest.json").read_text())
    if manifest.get("version") != 1:
        raise ValueError("Unsupported manifest version")
    directories = manifest.get("directories", {})
    links = manifest.get("links", {})
    validate_links(links)
    for relative in directories:
        if relative in {"", "."} or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ValueError("Invalid backup directory")
    files = inventory(backup / "data")
    if set(files) != set(manifest["files"]):
        raise ValueError("Backup inventory does not match the manifest")
    for relative in links:
        if relative in files or relative in directories:
            raise ValueError("Conflicting symbolic link path")
    for relative in set(files) | set(directories) | set(links):
        if any(str(parent) in links for parent in Path(relative).parents):
            raise ValueError("Symbolic link parent is another symbolic link")
    # Verify everything before writing the target.
    for relative, path in files.items():
        if digest(path) != manifest["files"][relative]["sha256"]:
            raise ValueError("Backup checksum mismatch")
        if manifest["files"][relative]["sqlite"]:
            with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as database:
                if database.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                    raise ValueError("SQLite restore failed its integrity check")
    target.mkdir(mode=0o700, parents=True, exist_ok=True)
    for relative in directories:
        (target / relative).mkdir(mode=0o700, parents=True, exist_ok=True)
    for relative, path in files.items():
        output = target / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, output)
        output.chmod(manifest["files"][relative]["mode"] & 0o777)
    for relative, link_target in links.items():
        output = target / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        output.symlink_to(link_target)
    for relative, mode in sorted(directories.items(), reverse=True):
        (target / relative).chmod(mode & 0o777)
    print(f"Restore complete: {len(files)} files", flush=True)


def copy_stable_sqlite(source, directory, attempts=3):
    source = Path(source)
    wal = Path(str(source) + "-wal")
    output = Path(directory) / source.name

    def identity(path):
        try:
            info = path.stat()
        except FileNotFoundError:
            return None
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("SQLite snapshots require regular files")
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)

    # A read-only WAL database may lack sidecars that SQLite needs to create.
    # Copy a stable DB/WAL pair locally; never create sidecars on the source.
    for _ in range(attempts):
        before = (identity(source), identity(wal))
        try:
            shutil.copyfile(source, output)
            if before[1] is not None:
                shutil.copyfile(wal, Path(str(output) + "-wal"))
            after = (identity(source), identity(wal))
        except FileNotFoundError:
            after = None
        if before[0] is not None and before == after:
            return output
        for copied in Path(directory).iterdir():
            copied.unlink()
    raise ValueError("SQLite files changed during the local snapshot")


def backup_sqlite(source, target):
    deadline = time.monotonic() + 120

    def progress(status, remaining, total):
        if time.monotonic() > deadline:
            raise TimeoutError("SQLite backup exceeded its deadline")

    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=5)) as connection:
        with closing(sqlite3.connect(target)) as backup:
            connection.backup(backup, pages=256, progress=progress)
            backup.execute("PRAGMA journal_mode=DELETE")
            if backup.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                raise ValueError("SQLite snapshot failed its integrity check")


def snapshot_database(source, target):
    try:
        backup_sqlite(source, target)
    except sqlite3.OperationalError as error:
        if error.sqlite_errorcode & 0xff not in {sqlite3.SQLITE_CANTOPEN, sqlite3.SQLITE_READONLY}:
            raise
        with source.open("rb") as stream:
            header = stream.read(20)
        if header[18:20] != b"\x02\x02":
            raise
        target.unlink(missing_ok=True)
        with tempfile.TemporaryDirectory(prefix="sqlite-backup-") as directory:
            local = copy_stable_sqlite(source, directory)
            backup_sqlite(local, target)


def snapshot(source, destination):
    source = Path(source).resolve(strict=True)
    destination = Path(destination).resolve()
    if source == destination or source in destination.parents:
        raise ValueError("Backup destination must be outside the source")
    os.umask(0o077)
    destination.mkdir(parents=True, exist_ok=True)
    completed = sorted(p for p in destination.iterdir() if not p.name.startswith(".") and (p / "manifest.json").is_file())
    previous = completed[-1] if completed else None
    try:
        previous_files = json.loads((previous / "manifest.json").read_text())["files"] if previous else {}
    except (KeyError, OSError, TypeError, ValueError):
        previous_files = {}
    name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    staging = destination / (".incomplete-" + name)
    directories = {}
    links = {}
    entries = inventory(source, directories, links)
    databases = set()
    for relative, path in entries.items():
        with path.open("rb") as stream:
            if stream.read(16) == SQLITE_HEADER:
                databases.add(relative)
            elif path.suffix.lower() in {".db", ".sqlite", ".sqlite3"}:
                raise ValueError("Unknown or encrypted database requires its native backup mechanism")
    # SQLite sidecars belong to the online snapshot, never to the file copy.
    sidecars = {name + suffix for name in databases for suffix in ("-wal", "-shm", "-journal")}
    records = {}
    staging.mkdir(mode=0o700)
    try:
        for relative, path in entries.items():
            if relative in sidecars:
                continue
            target = staging / "data" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if relative in databases:
                snapshot_database(path, target)
            else:
                # Refuse known live database stores that need a native export.
                if path.name in {"data.mdb", "lock.mdb", "CURRENT"} or path.suffix in {".sst", ".ldb"}:
                    raise ValueError("Non-SQLite database requires its native backup mechanism")
                before = path.stat()
                shutil.copyfile(path, target)
                after = path.stat()
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise ValueError("A source file changed while being copied")
            checksum = digest(target)
            if reusable(previous, previous_files, relative, checksum):
                target.unlink()
                os.link(previous / "data" / relative, target)
            records[relative] = {
                "mode": stat.S_IMODE(path.stat().st_mode) & 0o777,
                "sha256": checksum,
                "sqlite": relative in databases,
            }
        final_links = {}
        if set(inventory(source, links=final_links)) - sidecars != set(entries) - sidecars or final_links != links:
            raise ValueError("The source inventory changed during backup")
        (staging / "data").mkdir(exist_ok=True)
        manifest = {"directories": directories, "files": records, "links": links, "created": name, "version": 1}
        (staging / "manifest.json").write_text(json.dumps(manifest, sort_keys=True) + "\n")
        staging.rename(destination / name)
    except BaseException:
        shutil.rmtree(staging)
        raise
    print(f"Backup complete: {len(records)} files, {len(databases)} SQLite databases", flush=True)


if __name__ == "__main__":
    try:
        if len(sys.argv) == 4 and sys.argv[1] == "restore":
            restore(sys.argv[2], sys.argv[3])
        elif len(sys.argv) == 3:
            snapshot(sys.argv[1], sys.argv[2])
        else:
            raise ValueError("Use: backup.py SOURCE DESTINATION | backup.py restore BACKUP EMPTY_TARGET")
    except Exception as error:
        # Exceptions may contain paths or application data; expose only the class.
        print(f"Backup failed: {type(error).__name__}", file=sys.stderr, flush=True)
        sys.exit(1)
