from pathlib import Path

from vesper.process_policy import ProcessBudget, ProcessMonitor
from vesper.storage import Storage


def _storage(path: Path) -> Storage:
    storage = Storage(path / "vesper.sqlite3")
    storage.migrate()
    storage.start()
    storage.write(lambda c: c.execute("INSERT OR IGNORE INTO processes(process_id,status,origin,created_at,updated_at) VALUES('p1','RUNNING','test','now','now')"))
    return storage


def test_budget_consumption_survives_restart(tmp_path: Path):
    first = _storage(tmp_path)
    budget = ProcessBudget.load(first, "p1", default_tokens=100, default_seconds=60)
    assert budget.consume(tokens=25, seconds=10)
    first.stop()

    second = _storage(tmp_path)
    restored = ProcessBudget.load(second, "p1", default_tokens=100, default_seconds=60)
    assert (restored.tokens, restored.seconds) == (75, 50)
    second.stop()


def test_monitor_progress_survives_restart(tmp_path: Path):
    first = _storage(tmp_path)
    monitor = ProcessMonitor.load(first, "p1", cadence_seconds=30, max_checks=2)
    assert monitor.check(now=100, condition=lambda: True) is True
    first.stop()

    second = _storage(tmp_path)
    restored = ProcessMonitor.load(second, "p1", cadence_seconds=30, max_checks=2)
    assert restored.check(now=110, condition=lambda: False) is None
    assert restored.check(now=130, condition=lambda: True) is True
    second.stop()


def test_runtime_state_is_canonical_and_bounded(tmp_path: Path):
    storage = _storage(tmp_path)
    budget = ProcessBudget.load(storage, "p1", default_tokens=2, default_seconds=2)
    assert budget.consume(tokens=3, seconds=0) is False
    row = storage.write(lambda c: c.execute("SELECT budget_tokens_remaining,budget_seconds_remaining FROM process_runtime_state WHERE process_id='p1'").fetchone())
    assert (row["budget_tokens_remaining"], row["budget_seconds_remaining"]) == (2, 2)
    storage.stop()
