from pathlib import Path

import pytest

from vesper.execution_graph import ExecutionGraphStore, GraphNodeType, GraphValidationError
from vesper.storage import Storage


def _store(tmp_path: Path):
    storage = Storage(tmp_path / "vesper.db")
    storage.migrate()
    storage.start()
    return storage, ExecutionGraphStore(storage)


def test_graph_revision_is_immutable_and_audited(tmp_path: Path):
    storage, graphs = _store(tmp_path)
    try:
        graph = graphs.create_graph(process_id="p")
        revision = graphs.request_revision(graph.graph_id, reason="need additional validation", requested_by="lane:review")
        assert revision.status == "REQUESTED"
        graphs.approve_revision(graph.graph_id, revision.revision_id, approved_by="director")
        restored = graphs.get_revisions(graph.graph_id)
        assert restored[0].status == "APPROVED"
        assert restored[0].approved_by == "director"
    finally:
        storage.stop()


def test_revision_requires_reason_and_actor(tmp_path: Path):
    storage, graphs = _store(tmp_path)
    try:
        graph = graphs.create_graph(process_id="p")
        with pytest.raises(GraphValidationError):
            graphs.request_revision(graph.graph_id, reason="", requested_by="lane")
        with pytest.raises(GraphValidationError):
            graphs.request_revision(graph.graph_id, reason="change", requested_by="")
    finally:
        storage.stop()


def test_revision_cannot_be_approved_twice(tmp_path: Path):
    storage, graphs = _store(tmp_path)
    try:
        graph = graphs.create_graph(process_id="p")
        revision = graphs.request_revision(graph.graph_id, reason="change", requested_by="lane")
        graphs.approve_revision(graph.graph_id, revision.revision_id, approved_by="director")
        with pytest.raises(GraphValidationError):
            graphs.approve_revision(graph.graph_id, revision.revision_id, approved_by="director")
    finally:
        storage.stop()


def test_partial_revision_preserves_completed_nodes(tmp_path: Path):
    storage, graphs = _store(tmp_path)
    try:
        graph = graphs.create_graph(process_id="p")
        graphs.add_node(graph.graph_id, node_id="done", node_type=GraphNodeType.LANE)
        graphs.add_node(graph.graph_id, node_id="pending", node_type=GraphNodeType.LANE)
        graphs.start_node(graph.graph_id, "done")
        graphs.complete_node(graph.graph_id, "done")
        revision = graphs.request_revision(graph.graph_id, reason="new evidence", requested_by="main", target_node_ids=("pending",))
        graphs.approve_revision(graph.graph_id, revision.revision_id, approved_by="director")
        graphs.apply_revision(graph.graph_id, revision.revision_id)
        restored = graphs.get_graph(graph.graph_id)
        assert next(node for node in restored.nodes if node.node_id == "done").status.value == "COMPLETED"
        assert next(node for node in restored.nodes if node.node_id == "pending").status.value == "PENDING"
    finally:
        storage.stop()
