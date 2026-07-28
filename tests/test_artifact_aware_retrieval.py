from vesper.artifacts import ArtifactStore
from vesper.memory import MemoryStore, RetrievalStatus
from vesper.storage import Storage


def test_retrieval_can_require_artifact_provenance(tmp_path):
    storage = Storage(tmp_path / "vesper.db")
    storage.migrate()
    storage.start()
    storage.write(lambda c: c.execute("INSERT INTO processes(process_id,status,origin,created_at,updated_at) VALUES('p1','RUNNING','test','now','now')"))
    artifacts = ArtifactStore(tmp_path, storage)
    artifact = artifacts.publish_typed(
        artifact_type="research_note", schema_version=1, process_id="p1",
        producer_invocation_id="inv1", provenance={"source_refs": ["src-1"]},
        content={"text": "artifact evidence"},
    )
    memories = MemoryStore(storage)
    memories.put(kind="artifact_summary", payload={"text": "artifact evidence"}, provenance={"source": "artifact", "artifact_id": artifact.artifact_id, "artifact_type": "research_note", "source_refs": ["src-1"]})
    memories.put(kind="note", payload={"text": "artifact evidence"}, provenance={"source": "director"})
    result = memories.retrieve("artifact evidence", artifact_type="research_note")
    assert result.status == RetrievalStatus.RESOLVED
    assert len(result.items) == 1
    assert result.items[0].provenance["artifact_id"] == artifact.artifact_id