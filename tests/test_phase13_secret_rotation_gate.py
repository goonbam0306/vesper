from vesper.connections import ConnectionStore
from vesper.secret_store import EphemeralTestSecretStore
from vesper.storage import Storage


def test_secret_rotation_replaces_value_without_exposing_old_secret(tmp_path):
    storage = Storage(tmp_path / "rotation.db")
    storage.migrate()
    storage.start()
    secrets = EphemeralTestSecretStore()
    store = ConnectionStore(storage, secret_store=secrets)
    old_ref = secrets.put("old-secret", label="provider")
    store.register_secret_metadata(provider="test", label="provider", secret_ref=old_ref)
    new_ref = store.rotate_secret(old_ref, "new-secret", label="provider")
    assert new_ref != old_ref
    assert secrets.get(old_ref) is None
    assert secrets.get(new_ref) == "new-secret"
    rows = store.list_secret_metadata()
    assert [row["secret_ref"] for row in rows] == [new_ref]
    storage.stop()


def test_rotation_rejects_invalid_reference(tmp_path):
    store = ConnectionStore(Storage(tmp_path / "rotation.db"), secret_store=EphemeralTestSecretStore())
    try:
        store.rotate_secret("plain-text", "new-secret", label="provider")
    except Exception as exc:
        assert "credential" in str(exc).lower() or "ref" in str(exc).lower()
    else:
        raise AssertionError("invalid secret reference was accepted")
    store.storage.stop()
