from pathlib import Path

from vesper.memory import MemoryStore
from vesper.storage import Storage


def test_context_pack_admission_is_bounded_and_prioritized(tmp_path: Path):
    storage = Storage(tmp_path / "vesper.db")
    storage.migrate()
    storage.start()
    store = MemoryStore(storage)
    first = store.put(kind="note", payload={"text": "alpha project decision"})
    second = store.put(kind="note", payload={"text": "alpha implementation detail"})
    pack = store.admit_context_pack("alpha", token_budget=6, limit=1)
    assert pack.query == "alpha"
    assert len(pack.items) == 1
    assert pack.items[0].payload["text"] == "alpha project decision"
    assert pack.token_budget == 6
    assert second.memory_id not in {item.memory_id for item in pack.items}
    storage.stop()


def test_context_pack_rejects_invalid_budget(tmp_path: Path):
    storage = Storage(tmp_path / "vesper.db")
    storage.migrate()
    storage.start()
    try:
        MemoryStore(storage).admit_context_pack("x", token_budget=0)
    except ValueError as exc:
        assert "token_budget" in str(exc)
    else:
        raise AssertionError("invalid budget accepted")
    storage.stop()


def test_context_pack_preserves_retrieval_status(tmp_path: Path):
    storage = Storage(tmp_path / "vesper.db")
    storage.migrate()
    storage.start()
    store = MemoryStore(storage)
    store.put(kind="note", payload={"text": "unique"})
    pack = store.admit_context_pack("unique", token_budget=20)
    assert pack.status.value == "RESOLVED"
    storage.stop()
