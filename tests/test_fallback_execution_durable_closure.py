from vesper.fallback_execution import FallbackExecutionRecord, FallbackExecutionStore
from vesper.kernel import Kernel
from vesper.storage import Storage


def test_fallback_execution_record_survives_restart_and_is_queryable(tmp_path):
    db = tmp_path / "vesper.sqlite3"
    storage = Storage(db)
    storage.migrate()
    storage.start()
    process = Kernel(storage).submit("fallback")
    record = FallbackExecutionRecord.create(
        process.process_id,
        inferred_function_label="research",
        disposition="VERIFIED",
        cognitive_operations=("retrieve", "analyze"),
        normalized_input_shape={"type": "text"},
        normalized_output_shape={"type": "report"},
        normalized_context_shape={"scope": "local"},
        tool_profile=("read",),
        evaluation_dimensions=("quality",),
        permission_shape=("read",),
        domain_tags=("docs",),
        selected_model_route="local",
        verification_ref="verify:1",
        artifact_refs=("artifact:1",),
    )
    FallbackExecutionStore(storage).save(record)
    storage.stop()

    restarted = Storage(db)
    restarted.migrate()
    restarted.start()
    rows = FallbackExecutionStore(restarted).list_for_process(process.process_id)
    assert len(rows) == 1
    assert rows[0].fallback_execution_id == record.fallback_execution_id
    assert rows[0].cognitive_operations == ("retrieve", "analyze")
    assert rows[0].normalized_output_shape == {"type": "report"}
    restarted.stop()


def test_fallback_record_rejects_missing_identity(tmp_path):
    storage = Storage(tmp_path / "vesper.sqlite3")
    storage.migrate()
    storage.start()
    store = FallbackExecutionStore(storage)
    record = FallbackExecutionRecord.create(
        "", inferred_function_label="", disposition="FAILED",
        cognitive_operations=(), normalized_input_shape={}, normalized_output_shape={},
        normalized_context_shape={}, tool_profile=(), evaluation_dimensions=(), permission_shape=(),
    )
    try:
        store.save(record)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
    finally:
        storage.stop()
