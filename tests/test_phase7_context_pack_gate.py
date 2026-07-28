from vesper.memory import MemoryStore
from vesper.storage import Storage


def test_phase7_gate_compacts_large_memory_into_bounded_context_pack(tmp_path):
    storage = Storage(tmp_path / "gate.db")
    storage.migrate()
    storage.start()
    store = MemoryStore(storage)
    for index in range(30):
        store.put(kind="note", payload={"text": f"project alpha fact {index}"})
    pack = store.admit_context_pack("alpha", token_budget=12, limit=30)
    assert pack.status.value in {"RESOLVED", "AMBIGUOUS", "CONFLICT"}
    assert 0 < len(pack.items) < 30
    assert sum(max(1, len(str(item.payload).split())) for item in pack.items) <= 12
    storage.stop()
