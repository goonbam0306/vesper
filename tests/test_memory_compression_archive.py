from vesper.memory import MemoryStore
from vesper.storage import Storage


def _store(tmp_path):
    storage = Storage(tmp_path / "memory.db")
    storage.migrate()
    storage.start()
    return storage, MemoryStore(storage)


def test_compress_preserves_provenance_and_archives_source(tmp_path):
    storage, memories = _store(tmp_path)
    first = memories.put(kind="note", payload={"text": "first fact"}, provenance={"source": "director", "ref": "a"})
    second = memories.put(kind="note", payload={"text": "second fact"}, provenance={"source": "director", "ref": "b"})
    compressed = memories.compress((first.memory_id, second.memory_id), summary="first and second facts")
    assert compressed.kind == "summary"
    assert compressed.payload["text"] == "first and second facts"
    assert compressed.provenance["compression"]["source_memory_ids"] == [first.memory_id, second.memory_id]
    assert memories.get(first.memory_id).validity == "ARCHIVED"
    assert memories.get(second.memory_id).validity == "ARCHIVED"
    storage.stop()


def test_compress_requires_existing_memories_and_summary(tmp_path):
    storage, memories = _store(tmp_path)
    try:
        memories.compress(("missing",), summary="x")
    except ValueError as exc:
        assert "memory" in str(exc)
    else:
        raise AssertionError("missing source accepted")
    try:
        memories.compress((), summary="x")
    except ValueError as exc:
        assert "source" in str(exc)
    else:
        raise AssertionError("empty source accepted")
    storage.stop()
