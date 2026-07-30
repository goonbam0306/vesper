import json

import pytest

from vesper.artifacts import ArtifactStore, ArtifactValidationError
from vesper.storage import Storage


def test_safe_reset_exports_selected_state_and_preserves_protected_runtime(tmp_path):
    storage = Storage(tmp_path / "vesper.sqlite3")
    storage.migrate(); storage.start()
    store = ArtifactStore(tmp_path, storage)
    artifact = store.publish(b"reset-me")
    export_dir = tmp_path / "export"
    receipt = store.safe_reset(principal="director", scope=[artifact.artifact_id], export_destination=export_dir, export_before_reset=True)
    assert receipt["scope"] == [artifact.artifact_id]
    assert (export_dir / "manifest.json").is_file()
    assert not artifact.path.exists()
    assert storage.connect().execute("SELECT 1 FROM artifacts WHERE artifact_id=?", (artifact.artifact_id,)).fetchone() is None
    assert storage.connect().execute("SELECT COUNT(*) FROM safe_reset_receipts").fetchone()[0] == 1
    storage.stop()


def test_safe_reset_rejects_unauthorized_or_protected_scope(tmp_path):
    storage = Storage(tmp_path / "vesper.sqlite3"); storage.migrate(); storage.start()
    store = ArtifactStore(tmp_path, storage)
    with pytest.raises(ArtifactValidationError):
        store.safe_reset(principal="user", scope=["runtime"])
    with pytest.raises(ArtifactValidationError):
        store.safe_reset(principal="director", scope=["credentials"])
    storage.stop()