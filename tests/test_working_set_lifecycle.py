from vesper.memory import MemoryStore
from vesper.storage import Storage


def test_l2_working_set_checkpoint_evict_promote_discard_preserves_l3(tmp_path):
    storage = Storage(tmp_path / "memory.db")
    storage.migrate()
    storage.start()
    storage.write(lambda c: c.execute("INSERT INTO processes(process_id, status, origin, created_at, updated_at) VALUES('p1','RUNNING','test','now','now')"))
    memories = MemoryStore(storage)
    item = memories.put(kind="note", payload={"text": "durable fact"})

    memories.page_in("p1", item)
    assert memories.checkpoint("p1") == (item,)
    assert memories.evict("p1", item.memory_id) == item
    assert memories.l2("p1") == ()
    assert memories.get(item.memory_id) == item

    assert memories.promote("p1", item.memory_id) == item
    assert memories.l2("p1") == (item,)
    assert memories.discard("p1") == (item,)
    assert memories.l2("p1") == ()
    assert memories.get(item.memory_id) == item