import json

from vesper.artifacts import ArtifactStore
from vesper.storage import Storage


def test_safe_export_writes_manifest_and_excludes_secret_metadata(tmp_path):
    storage = Storage(tmp_path / "export.db")
    storage.migrate()
    storage.start()
    store = ArtifactStore(tmp_path, storage)
    artifact = store.publish(b"safe artifact", media_type="text/plain")
    storage.write(lambda c: c.execute("INSERT INTO secret_metadata(secret_ref, provider, label) VALUES ('secret://test/x', 'test', 'token')"))

    manifest = store.safe_export(tmp_path / "export")
    assert manifest["format"] == "vesper-safe-export-v1"
    assert manifest["artifacts"][0]["artifact_id"] == artifact.artifact_id
    text = (tmp_path / "export" / "manifest.json").read_text(encoding="utf-8")
    assert "secret://" not in text
    assert json.loads(text) == manifest
    storage.stop()


def test_safe_export_rejects_tampered_artifact(tmp_path):
    storage = Storage(tmp_path / "export.db")
    storage.migrate()
    storage.start()
    store = ArtifactStore(tmp_path, storage)
    artifact = store.publish(b"original")
    artifact.path.write_bytes(b"tampered")
    try:
        store.safe_export(tmp_path / "export")
    except RuntimeError as exc:
        assert "integrity" in str(exc)
    else:
        raise AssertionError("tampered artifact was exported")
    storage.stop()
