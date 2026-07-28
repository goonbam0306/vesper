from vesper.memory import MemoryStore
from vesper.storage import Storage


def test_context_pack_can_be_paged_in_and_archived(tmp_path):
    storage = Storage(tmp_path / "memory.db")
    storage.migrate()
    storage.start()
    storage.write(lambda c: c.execute("INSERT INTO processes(process_id,status,origin,created_at,updated_at) VALUES('p1','RUNNING','test','now','now')"))
    store = MemoryStore(storage)
    item = store.put(kind="note", payload={"text": "durable"})
    pack = store.admit_context_pack("durable", token_budget=10)
    assert pack.items
    store.page_in_pack("p1", pack)
    assert store.l2("p1")[0].memory_id == item.memory_id
    store.archive("p1")
    assert store.l2("p1") == ()
    assert store.get(item.memory_id).validity == "ARCHIVED"
    storage.stop()


def test_page_in_pack_rejects_foreign_pack(tmp_path):
    storage = Storage(tmp_path / "memory.db")
    storage.migrate()
    storage.start()
    store = MemoryStore(storage)
    try:
        store.page_in_pack("missing", object())
    except ValueError as exc:
        assert "ContextPack" in str(exc)
    else:
        raise AssertionError("foreign pack accepted")
    storage.stop()


def test_archive_requires_process(tmp_path):
    storage = Storage(tmp_path / "memory.db")
    storage.migrate()
    storage.start()
    try:
        MemoryStore(storage).archive("missing")
    except ValueError as exc:
        assert "process" in str(exc)
    else:
        raise AssertionError("missing process accepted")
    storage.stop()
