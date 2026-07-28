from vesper.backup import backup_database, restore_database
from vesper.storage import Storage


def test_backup_restore_validates_schema(tmp_path):
    source = tmp_path / "source.db"
    backup = tmp_path / "backup.db"
    restored = tmp_path / "restored.db"
    storage = Storage(source); storage.migrate(); storage.start()
    manifest = backup_database(source, backup)
    assert manifest["schema_version"] > 0
    restore_database(backup, restored, expected_schema_version=manifest["schema_version"])
    assert restored.exists()