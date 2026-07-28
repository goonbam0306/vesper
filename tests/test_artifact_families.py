from pathlib import Path

import pytest

from vesper.artifacts import ArtifactStore, ArtifactValidationError
from vesper.storage import Storage


def test_active_artifact_families_have_typed_constructor(tmp_path: Path):
    storage = Storage(tmp_path / "vesper.db")
    storage.migrate()
    storage.start()
    try:
        store = ArtifactStore(tmp_path, storage)
        for artifact_type in ("EvidencePack", "PatchSet", "VerificationReport"):
            artifact = store.publish_typed(
                artifact_type=artifact_type,
                schema_version=1,
                process_id="p",
                producer_invocation_id=f"i-{artifact_type}",
                provenance={"source_refs": ["source-1"]},
                content={"kind": artifact_type},
            )
            assert artifact.artifact_type == artifact_type
    finally:
        storage.stop()


def test_artifact_type_is_not_silently_coerced(tmp_path: Path):
    storage = Storage(tmp_path / "vesper.db")
    storage.migrate()
    storage.start()
    try:
        with pytest.raises(ArtifactValidationError):
            ArtifactStore(tmp_path, storage).publish_typed(
                artifact_type=123, schema_version=1, process_id="p",
                producer_invocation_id="i", provenance={}, content={},
            )
        with pytest.raises(ArtifactValidationError):
            ArtifactStore(tmp_path, storage).publish_typed(
                artifact_type="EvidencePack", schema_version=1, process_id="p",
                producer_invocation_id="i2", provenance={"source_refs": [7]}, content={},
            )
    finally:
        storage.stop()


def test_consumer_loads_typed_artifact_by_reference_and_rejects_wrong_type(tmp_path: Path):
    storage = Storage(tmp_path / "vesper.db")
    storage.migrate()
    storage.start()
    try:
        store = ArtifactStore(tmp_path, storage)
        artifact = store.publish_typed(artifact_type="EvidencePack", schema_version=1, process_id="p", producer_invocation_id="i", provenance={"source_refs": ["s"]}, content={"facts": []})
        loaded = store.load_typed(artifact.artifact_id, expected_type="EvidencePack")
        assert loaded.producer_invocation_id == "i"
        with pytest.raises(ArtifactValidationError):
            store.load_typed(artifact.artifact_id, expected_type="PatchSet")
    finally:
        storage.stop()
