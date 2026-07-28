import json
from pathlib import Path

import pytest

from vesper.artifacts import ArtifactStore, ArtifactEnvelope, ArtifactValidationError
from vesper.storage import Storage


def test_publish_typed_artifact_envelope_with_provenance(tmp_path: Path):
    storage = Storage(tmp_path / "vesper.db")
    storage.migrate()
    storage.start()
    try:
        store = ArtifactStore(tmp_path, storage)
        envelope = store.publish_typed(
            artifact_type="PatchSet",
            schema_version=1,
            process_id="process-1",
            producer_invocation_id="invocation-1",
            provenance={"source_refs": ["evidence-1"]},
            content={"files": ["a.py"]},
        )
        assert isinstance(envelope, ArtifactEnvelope)
        assert envelope.artifact_type == "PatchSet"
        assert envelope.schema_version == 1
        assert envelope.process_id == "process-1"
        assert envelope.producer_invocation_id == "invocation-1"
        assert envelope.content == {"files": ["a.py"]}
    finally:
        storage.stop()


def test_typed_artifact_rejects_invalid_metadata(tmp_path: Path):
    storage = Storage(tmp_path / "vesper.db")
    storage.migrate()
    storage.start()
    try:
        with pytest.raises(ArtifactValidationError):
            ArtifactStore(tmp_path, storage).publish_typed(
                artifact_type="", schema_version=0, process_id="p",
                producer_invocation_id="i", provenance={}, content={},
            )
    finally:
        storage.stop()
