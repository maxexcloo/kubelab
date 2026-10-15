import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest


MODULE = Path(__file__).resolve().parents[1] / "platform/backups/files/backup.py"
SPEC = importlib.util.spec_from_file_location("file_backup", MODULE)
BACKUP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BACKUP)


class FileBackupTests(unittest.TestCase):
    def test_live_wal_restore_and_unchanged_file_deduplication(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "attachment").write_bytes(b"unchanged attachment")
            (source / "attachment").chmod(0o750)
            (source / "empty").mkdir(mode=0o750)
            with sqlite3.connect(source / "state.sqlite") as writer:
                writer.execute("PRAGMA journal_mode=WAL")
                writer.execute("CREATE TABLE records (value TEXT)")
                writer.execute("INSERT INTO records VALUES ('committed')")
                writer.commit()
                (source / "state.sqlite").chmod(0o400)
                (source / "state.sqlite-wal").chmod(0o400)
                (source / "state.sqlite-shm").chmod(0o400)
                source.chmod(0o500)
                try:
                    BACKUP.snapshot(source, root / "backups")
                finally:
                    source.chmod(0o700)
                    for path in source.glob("state.sqlite*"):
                        path.chmod(0o600)
                writer.execute("INSERT INTO records VALUES ('later')")
                writer.commit()
                BACKUP.snapshot(source, root / "backups")
            first, second = sorted((root / "backups").iterdir())
            self.assertEqual((first / "data/attachment").stat().st_ino, (second / "data/attachment").stat().st_ino)
            self.assertFalse((first / "data/state.sqlite-wal").exists())
            BACKUP.restore(first, root / "restored")
            with sqlite3.connect(root / "restored/state.sqlite") as database:
                self.assertEqual(database.execute("SELECT value FROM records").fetchall(), [("committed",)])
            self.assertEqual((root / "restored/attachment").read_bytes(), b"unchanged attachment")
            self.assertEqual((root / "restored/attachment").stat().st_mode & 0o777, 0o750)
            self.assertEqual((root / "restored/empty").stat().st_mode & 0o777, 0o750)

    def test_restore_rejects_corruption_and_nonempty_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "file").write_bytes(b"original")
            BACKUP.snapshot(source, root / "backups")
            backup = next((root / "backups").iterdir())
            with self.assertRaises(ValueError):
                BACKUP.restore(backup, source)
            (backup / "data/file").write_bytes(b"corrupt")
            with self.assertRaises(ValueError):
                BACKUP.restore(backup, root / "restored")
            self.assertFalse((root / "restored").exists())
            BACKUP.snapshot(source, root / "backups")
            latest = sorted((root / "backups").iterdir())[-1]
            BACKUP.restore(latest, root / "recovered")
            self.assertEqual((root / "recovered/file").read_bytes(), b"original")
            (latest / "data/file").unlink()
            BACKUP.snapshot(source, root / "backups")
            latest = sorted((root / "backups").iterdir())[-1]
            BACKUP.restore(latest, root / "recovered-again")
            self.assertEqual((root / "recovered-again/file").read_bytes(), b"original")

    def test_rejects_symlinks_and_unknown_databases(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "link").symlink_to(root)
            with self.assertRaises(ValueError):
                BACKUP.snapshot(source, root / "backups")
            (source / "link").unlink()
            (source / "encrypted.db").write_bytes(b"opaque database")
            with self.assertRaises(ValueError):
                BACKUP.snapshot(source, root / "backups")

    def test_rejects_backup_destination_inside_source(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                BACKUP.snapshot(directory, Path(directory) / "backups")

    def test_preserves_internal_relative_symlinks_without_following_them(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            (source / "cache/blobs").mkdir(parents=True)
            (source / "cache/snapshots/revision").mkdir(parents=True)
            (source / "cache/blobs/model").write_bytes(b"model data")
            (source / "cache/snapshots/revision/model").symlink_to("../../blobs/model")
            (source / "models").symlink_to("cache/snapshots/revision", target_is_directory=True)
            BACKUP.snapshot(source, root / "backups")
            backup = next((root / "backups").iterdir())
            self.assertFalse((backup / "data/models").exists())
            BACKUP.restore(backup, root / "restored")
            self.assertTrue((root / "restored/models").is_symlink())
            self.assertEqual((root / "restored/models/model").read_bytes(), b"model data")
            self.assertEqual((root / "restored/cache/snapshots/revision/model").readlink(), Path("../../blobs/model"))

    def test_rejects_relative_link_escapes_on_backup_and_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "file").write_bytes(b"safe data")
            (source / "escape").symlink_to("../outside")
            with self.assertRaises(ValueError):
                BACKUP.snapshot(source, root / "backups")
            (source / "escape").unlink()
            BACKUP.snapshot(source, root / "backups")
            backup = next((root / "backups").iterdir())
            manifest = json.loads((backup / "manifest.json").read_text())
            manifest["links"] = {"link": "indirect", "indirect": "../outside"}
            (backup / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):
                BACKUP.restore(backup, root / "restored")
            self.assertFalse((root / "restored").exists())
