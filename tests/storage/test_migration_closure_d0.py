from pathlib import Path

import pytest

from vesper.storage import MigrationError, MigrationIdentityError, Storage


def write_migration(directory: Path, name: str, sql: str) -> None:
    directory.mkdir(exist_ok=True)
    (directory / name).write_text(sql, encoding="utf-8")


def applied(db: Path) -> list[tuple[int, str, str]]:
    storage = Storage(db)
    connection = storage.connect()
    try:
        return [tuple(row) for row in connection.execute("SELECT version,name,checksum FROM schema_migrations ORDER BY version")]
    finally:
        connection.close()


def test_fresh_database_applies_inventory_once_in_numeric_revision_order(tmp_path: Path):
    migrations = tmp_path / "migrations"
    write_migration(migrations, "010_late.sql", "CREATE TABLE late(id INTEGER);")
    write_migration(migrations, "002_early.sql", "CREATE TABLE early(id INTEGER);")
    storage = Storage(tmp_path / "fresh.sqlite3", migrations)
    storage.migrate()
    first = applied(tmp_path / "fresh.sqlite3")
    storage.migrate()
    assert [row[0] for row in first] == [2, 10]
    assert len(applied(tmp_path / "fresh.sqlite3")) == 2
    assert all(row[1] and row[2] for row in first)


def test_existing_gate_c_database_only_applies_pending_gate_d_revision_and_preserves_data(tmp_path: Path):
    migrations = tmp_path / "migrations"
    write_migration(migrations, "001_base.sql", "CREATE TABLE state(value TEXT); INSERT INTO state VALUES ('gate-c');")
    db = tmp_path / "upgrade.sqlite3"
    Storage(db, migrations).migrate()
    write_migration(migrations, "010_gate_d.sql", "CREATE TABLE gate_d(id INTEGER);")
    Storage(db, migrations).migrate()
    storage = Storage(db, migrations)
    connection = storage.connect()
    try:
        assert connection.execute("SELECT value FROM state").fetchone()[0] == "gate-c"
        assert [row[0] for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")] == [1, 10]
        assert connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='gate_d'").fetchone()
    finally:
        connection.close()


def test_duplicate_version_fails_before_database_schema_is_touched(tmp_path: Path):
    migrations = tmp_path / "migrations"
    write_migration(migrations, "001_one.sql", "CREATE TABLE one(id INTEGER);")
    write_migration(migrations, "001_two.sql", "CREATE TABLE two(id INTEGER);")
    with pytest.raises(MigrationIdentityError, match="duplicate migration version 1"):
        Storage(tmp_path / "duplicate.sqlite3", migrations).migrate()
    assert not (tmp_path / "duplicate.sqlite3").exists()


def test_failed_migration_rolls_back_schema_and_does_not_record_version(tmp_path: Path):
    migrations = tmp_path / "migrations"
    write_migration(migrations, "001_ok.sql", "CREATE TABLE preserved(id INTEGER);")
    write_migration(migrations, "002_bad.sql", "CREATE TABLE half_applied(id INTEGER); THIS IS INVALID SQL;")
    db = tmp_path / "failed.sqlite3"
    with pytest.raises(MigrationError):
        Storage(db, migrations).migrate()
    storage = Storage(db, migrations)
    connection = storage.connect()
    try:
        assert [row[0] for row in connection.execute("SELECT version FROM schema_migrations")] == [1]
        assert connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='preserved'").fetchone()
        assert not connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='half_applied'").fetchone()
    finally:
        connection.close()


def test_applied_migration_checksum_change_is_detected(tmp_path: Path):
    migrations = tmp_path / "migrations"
    path = migrations / "001_base.sql"
    write_migration(migrations, path.name, "CREATE TABLE baseline(id INTEGER);")
    db = tmp_path / "identity.sqlite3"
    Storage(db, migrations).migrate()
    path.write_text("CREATE TABLE altered(id INTEGER);", encoding="utf-8")
    with pytest.raises(MigrationIdentityError, match="identity changed"):
        Storage(db, migrations).migrate()
