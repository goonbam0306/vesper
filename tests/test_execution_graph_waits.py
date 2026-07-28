from pathlib import Path

import pytest

from vesper.execution_graph import ExecutionGraphStore, GraphNodeType, GraphValidationError
from vesper.storage import Storage


def _store(tmp_path: Path):
    storage = Storage(tmp_path / "vesper.db")
    storage.migrate()
    storage.start()
    return storage, ExecutionGraphStore(storage)


def test_approval_wait_is_durable_and_resumable(tmp_path: Path):
    storage, graphs = _store(tmp_path)
    try:
        graph = graphs.create_graph(process_id="p")
        graphs.add_node(graph.graph_id, node_id="approval", node_type=GraphNodeType.APPROVAL_WAIT)
        graphs.wait_node(graph.graph_id, "approval", wait_key="director-approval")
        assert graphs.get_wait(graph.graph_id, "approval").wait_key == "director-approval"
        graphs.resume_wait(graph.graph_id, "approval", payload={"approved": True})
        assert graphs.get_wait(graph.graph_id, "approval").resumed is True
        assert graphs.can_start(graph.graph_id, "approval") is True
    finally:
        storage.stop()


def test_user_input_wait_requires_nonempty_key(tmp_path: Path):
    storage, graphs = _store(tmp_path)
    try:
        graph = graphs.create_graph(process_id="p")
        graphs.add_node(graph.graph_id, node_id="input", node_type=GraphNodeType.USER_INPUT_WAIT)
        with pytest.raises(GraphValidationError):
            graphs.wait_node(graph.graph_id, "input", wait_key="")
    finally:
        storage.stop()


def test_wait_cannot_resume_twice(tmp_path: Path):
    storage, graphs = _store(tmp_path)
    try:
        graph = graphs.create_graph(process_id="p")
        graphs.add_node(graph.graph_id, node_id="approval", node_type=GraphNodeType.APPROVAL_WAIT)
        graphs.wait_node(graph.graph_id, "approval", wait_key="approval")
        graphs.resume_wait(graph.graph_id, "approval", payload={"approved": True})
        with pytest.raises(GraphValidationError):
            graphs.resume_wait(graph.graph_id, "approval", payload={"approved": False})
    finally:
        storage.stop()
    

def test_blocked_wait_is_durable_and_resumable(tmp_path: Path):
    storage, graphs = _store(tmp_path)
    try:
        graph = graphs.create_graph(process_id="p")
        graphs.add_node(graph.graph_id, node_id="blocked", node_type=GraphNodeType.LANE)
        graphs.wait_node(graph.graph_id, "blocked", wait_key="external-condition", blocked=True)
        graphs.resume_wait(graph.graph_id, "blocked", payload={"resolved": True})
        restored = graphs.get_wait(graph.graph_id, "blocked")
        assert restored.resumed is True
        assert restored.payload == {"resolved": True}
    finally:
        storage.stop()


def test_wait_survives_restart(tmp_path: Path):
    storage, graphs = _store(tmp_path)
    graph = graphs.create_graph(process_id="p")
    graphs.add_node(graph.graph_id, node_id="input", node_type=GraphNodeType.USER_INPUT_WAIT)
    graphs.wait_node(graph.graph_id, "input", wait_key="question")
    storage.stop()
    storage.start()
    try:
        restored = ExecutionGraphStore(storage).get_wait(graph.graph_id, "input")
        assert restored.resumed is False
        assert restored.wait_key == "question"
    finally:
        storage.stop()
    
    