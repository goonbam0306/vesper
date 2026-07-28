from pathlib import Path

import pytest

from vesper.execution_graph import GraphNodeStatus, GraphNodeType, ExecutionGraphStore, GraphValidationError
from vesper.storage import Storage


def test_durable_graph_and_nodes(tmp_path: Path):
    storage = Storage(tmp_path / "vesper.db")
    storage.migrate()
    storage.start()
    try:
        graphs = ExecutionGraphStore(storage)
        graph = graphs.create_graph(process_id="process-1")
        node = graphs.add_node(graph.graph_id, node_id="a", node_type=GraphNodeType.LANE)
        assert node.status is GraphNodeStatus.PENDING
        restored = ExecutionGraphStore(storage).get_graph(graph.graph_id)
        assert restored.process_id == "process-1"
        assert restored.nodes[0].node_id == "a"
    finally:
        storage.stop()


def test_direct_is_not_a_graph_node_type(tmp_path: Path):
    storage = Storage(tmp_path / "vesper.db")
    storage.migrate()
    storage.start()
    try:
        graphs = ExecutionGraphStore(storage)
        graph = graphs.create_graph(process_id="p")
        with pytest.raises(GraphValidationError):
            graphs.add_node(graph.graph_id, node_id="x", node_type="DIRECT")
    finally:
        storage.stop()


def test_dependency_is_durable_and_predecessor_must_complete(tmp_path: Path):
    storage = Storage(tmp_path / "vesper.db")
    storage.migrate()
    storage.start()
    try:
        graphs = ExecutionGraphStore(storage)
        graph = graphs.create_graph(process_id="p")
        graphs.add_node(graph.graph_id, node_id="a", node_type=GraphNodeType.DETERMINISTIC_OPERATION, operation_name="pytest")
        graphs.add_node(graph.graph_id, node_id="b", node_type=GraphNodeType.LANE, dependencies=("a",))
        assert graphs.can_start(graph.graph_id, "b") is False
        graphs.complete_node(graph.graph_id, "a")
        assert graphs.can_start(graph.graph_id, "b") is True
    finally:
        storage.stop()


def test_unknown_dependency_is_rejected(tmp_path: Path):
    storage = Storage(tmp_path / "vesper.db")
    storage.migrate()
    storage.start()
    try:
        graphs = ExecutionGraphStore(storage)
        graph = graphs.create_graph(process_id="p")
        with pytest.raises(GraphValidationError):
            graphs.add_node(graph.graph_id, node_id="b", node_type=GraphNodeType.LANE, dependencies=("missing",))
    finally:
        storage.stop()


def test_graph_node_parent_lineage_is_preserved(tmp_path: Path):
    storage = Storage(tmp_path / "vesper.db")
    storage.migrate()
    storage.start()
    try:
        graphs = ExecutionGraphStore(storage)
        graph = graphs.create_graph(process_id="p")
        node = graphs.add_node(graph.graph_id, node_id="wait", node_type=GraphNodeType.APPROVAL_WAIT, parent_node_id="root")
        assert node.parent_node_id == "root"
    finally:
        storage.stop()


def test_recover_running_nodes_after_restart(tmp_path: Path):
    storage = Storage(tmp_path / "vesper.db")
    storage.migrate()
    storage.start()
    graphs = ExecutionGraphStore(storage)
    graph = graphs.create_graph(process_id="p")
    graphs.add_node(graph.graph_id, node_id="running", node_type=GraphNodeType.LANE)
    graphs.start_node(graph.graph_id, "running")
    storage.stop()
    storage.start()
    try:
        restored_graphs = ExecutionGraphStore(storage)
        assert restored_graphs.recover_running_nodes(graph.graph_id) == ("running",)
        assert restored_graphs.get_graph(graph.graph_id).nodes[0].status is GraphNodeStatus.PENDING
        assert restored_graphs.recover_running_nodes(graph.graph_id) == ()
    finally:
        storage.stop()
