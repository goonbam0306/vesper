from vesper.memory import MemoryStore, RetrievalStatus
from vesper.storage import Storage


def test_retrieval_filters_process_lane_producer_and_work_unit(tmp_path):
    storage = Storage(tmp_path / "vesper.db")
    storage.migrate()
    storage.start()
    try:
        memories = MemoryStore(storage)
        memories.put(
            kind="artifact_summary",
            payload={"text": "same research result"},
            provenance={
                "source": "artifact",
                "process_id": "p1",
                "lane_id": "research",
                "artifact_type": "note",
                "artifact_producer": "inv-1",
                "work_unit_id": "wu-1",
            },
        )
        memories.put(
            kind="artifact_summary",
            payload={"text": "same research result"},
            provenance={
                "source": "artifact",
                "process_id": "p2",
                "lane_id": "coding",
                "artifact_type": "note",
                "artifact_producer": "inv-2",
                "work_unit_id": "wu-2",
            },
        )
        result = memories.retrieve(
            "same research result",
            process_id="p1",
            lane_id="research",
            artifact_type="note",
            artifact_producer="inv-1",
            work_unit_id="wu-1",
        )
        assert result.status == RetrievalStatus.RESOLVED
        assert len(result.items) == 1
        assert result.items[0].provenance["process_id"] == "p1"
    finally:
        storage.stop()


def test_retrieval_filters_stale_matches_with_same_context(tmp_path):
    storage = Storage(tmp_path / "vesper.db")
    storage.migrate()
    storage.start()
    try:
        memories = MemoryStore(storage)
        item = memories.put(
            kind="note",
            payload={"text": "context fact"},
            provenance={"process_id": "p1", "lane_id": "research", "work_unit_id": "wu-1"},
            validity="VALID",
            memory_id="m1",
        )
        memories.put(
            kind="note",
            payload={"text": "context fact"},
            provenance={"process_id": "p1", "lane_id": "research", "work_unit_id": "wu-1"},
            validity="STALE",
            memory_id=item.memory_id,
        )
        result = memories.retrieve(
            "context fact", process_id="p1", lane_id="research", work_unit_id="wu-1"
        )
        assert result.status == RetrievalStatus.STALE_ONLY
        assert result.items[0].validity == "STALE"
    finally:
        storage.stop()


def test_context_pack_accepts_context_dimensions(tmp_path):
    storage = Storage(tmp_path / "vesper.db")
    storage.migrate()
    storage.start()
    try:
        memories = MemoryStore(storage)
        memories.put(
            kind="note",
            payload={"text": "bounded context"},
            provenance={"process_id": "p1", "lane_id": "research", "work_unit_id": "wu-1"},
        )
        pack = memories.admit_context_pack(
            "bounded context",
            token_budget=20,
            process_id="p1",
            lane_id="research",
            work_unit_id="wu-1",
        )
        assert len(pack.items) == 1
    finally:
        storage.stop()
