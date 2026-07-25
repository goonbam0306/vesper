import json
from pathlib import Path

from vesper.api import Runtime


class _FakeRuntime(Runtime):
    def invoke_default_model(self, process_id, prompt, *, context_items=()):
        return "VESPER_DIRECTOR_READY"


def test_conversation_projection_persists_and_context_is_bounded(tmp_path: Path):
    runtime = Runtime(tmp_path)
    runtime.start()
    process = runtime.kernel.submit("director", volatile=False)
    conversation = runtime.conversations.create(process.process_id)
    for index in range(20):
        runtime.conversations.append(conversation["conversation_id"], "USER", f"turn {index} unrelated")
        runtime.conversations.append(conversation["conversation_id"], "ASSISTANT", f"answer {index}")
    runtime.conversations.append(conversation["conversation_id"], "USER", "what is Orion?")
    runtime.conversations.append(conversation["conversation_id"], "ASSISTANT", "Orion is the code name")
    items = runtime.conversations.context_items(conversation["conversation_id"], "what was my code name Orion?")
    assert len(items) <= 6
    assert any("Orion" in item["content"] for item in items)
    assert len(runtime.conversations.messages(conversation["conversation_id"])) == 42
    runtime.stop()


def test_conversation_invoke_commits_canonical_nonempty_assistant_message(tmp_path: Path):
    runtime = _FakeRuntime(tmp_path)
    runtime.start()
    process = runtime.kernel.submit("director", volatile=False)
    conversation = runtime.conversations.create(process.process_id)
    from vesper.api import create_app
    from fastapi.testclient import TestClient
    client = TestClient(create_app(runtime), base_url="http://127.0.0.1")
    response = client.post("/api/model/invoke", headers={"X-Vesper-Bootstrap": runtime.bootstrap_token}, json={"conversation_id": conversation["conversation_id"], "prompt": "Reply with exactly: VESPER_DIRECTOR_READY"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["assistant_message"]["role"] == "ASSISTANT"
    assert len(payload["assistant_message"]["content"]) > 0
    messages = runtime.conversations.messages(conversation["conversation_id"])
    assert [message["role"] for message in messages] == ["USER", "ASSISTANT"]
    assert messages[1]["message_id"] == payload["assistant_message"]["message_id"]
    assert len([message for message in messages if message["role"] == "ASSISTANT"]) == 1
    runtime.stop()


def test_ask_task_intent_requires_canonical_commit_before_success(tmp_path: Path):
    class TaskRuntime(_FakeRuntime):
        pass
    runtime = TaskRuntime(tmp_path)
    runtime.start()
    process = runtime.kernel.submit("director", volatile=False)
    conversation = runtime.conversations.create(process.process_id)
    from vesper.api import create_app
    from fastapi.testclient import TestClient
    client = TestClient(create_app(runtime), base_url="http://127.0.0.1")
    response = client.post("/api/model/invoke", headers={"X-Vesper-Bootstrap": runtime.bootstrap_token}, json={"conversation_id": conversation["conversation_id"], "prompt": "할 일로 Vesper 업그레이드 하기 추가해줘"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["action"]["entity_type"] == "task"
    assert payload["action"]["commit_status"] == "COMMITTED"
    assert payload["action"]["task"]["title"] == "Vesper 업그레이드 하기"
    assert len(runtime.core_apps.list_tasks()) == 1
    assert "추가했습니다" in payload["assistant_message"]["content"]
    runtime.stop()


def test_task_action_failure_is_visible_and_not_success(tmp_path: Path):
    class FailingCore:
        def __init__(self, delegate):
            self.delegate = delegate

        def create_task(self, *args, **kwargs):
            from vesper.core_apps import CoreAppError
            raise CoreAppError("forced task failure")

        def list_tasks(self):
            return self.delegate.list_tasks()

    runtime = _FakeRuntime(tmp_path)
    runtime.core_apps = FailingCore(runtime.core_apps)
    runtime.start()
    process = runtime.kernel.submit("director", volatile=False)
    conversation = runtime.conversations.create(process.process_id)
    from vesper.api import create_app
    from fastapi.testclient import TestClient
    response = TestClient(create_app(runtime), base_url="http://127.0.0.1").post(
        "/api/model/invoke",
        headers={"X-Vesper-Bootstrap": runtime.bootstrap_token},
        json={"conversation_id": conversation["conversation_id"], "prompt": "할 일로 실패 작업 추가해줘"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ACTION_FAILED"
    assert payload["action"] == {
        "entity_type": "task",
        "supported_chat_action": "CREATE_TASK",
        "commit_status": "FAILED",
        "error_code": "CORE_APP_ERROR",
        "message": "forced task failure",
    }
    assert "추가했습니다" not in payload["assistant_message"]["content"]
    assert "Task에 추가하지 못했습니다" in payload["assistant_message"]["content"]
    assert runtime.core_apps.list_tasks() == []
    assert runtime.conversations.messages(conversation["conversation_id"])[-1]["content"] == payload["assistant_message"]["content"]
    # A failed action still has a Director submission provenance record.
    assert runtime.storage.write(lambda c: c.execute("SELECT COUNT(*) AS count FROM command_requests").fetchone()["count"]) == 1
    row = runtime.storage.write(lambda c: c.execute("SELECT outputs_json, effects_json FROM process_results WHERE process_id=?", (payload["process_id"],)).fetchone())
    assert row is not None
    result_outputs = json.loads(row["outputs_json"])
    result_effects = json.loads(row["effects_json"])
    assert result_outputs["status"] == "ACTION_FAILED"
    assert result_outputs["action"]["commit_status"] == "FAILED"
    assert result_effects == {}
    state = runtime.kernel.get(payload["process_id"])
    assert state.status == "FAILED"
    assert payload["action"]["commit_status"] == "FAILED"
    assert runtime.storage.write(lambda c: c.execute("SELECT COUNT(*) AS count FROM tasks").fetchone()["count"]) == 0
    runtime.stop()


def test_empty_model_output_is_not_reported_as_success(tmp_path: Path):
    class EmptyRuntime(Runtime):
        def invoke_default_model(self, process_id, prompt, *, context_items=()):
            return ""
    runtime = EmptyRuntime(tmp_path)
    runtime.start()
    process = runtime.kernel.submit("director", volatile=False)
    conversation = runtime.conversations.create(process.process_id)
    from vesper.api import create_app
    from fastapi.testclient import TestClient
    response = TestClient(create_app(runtime), base_url="http://127.0.0.1").post("/api/model/invoke", headers={"X-Vesper-Bootstrap": runtime.bootstrap_token}, json={"conversation_id": conversation["conversation_id"], "prompt": "hello"})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "MODEL_EMPTY_OUTPUT"
    assert runtime.conversations.messages(conversation["conversation_id"])[-1]["role"] == "ERROR"
    runtime.stop()