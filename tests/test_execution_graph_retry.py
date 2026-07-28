from pathlib import Path

import pytest

from vesper.execution_graph import ExecutionGraphStore, GraphNodeType, GraphNodeStatus, GraphValidationError
from vesper.storage import Storage


def test_node_retry_is_bounded(tmp_path: Path):
    storage = Storage(tmp_path / "vesper.db")
    storage.migrate()
    storage.start()
    try:
        graphs = ExecutionGraphStore(storage)
        graph = graphs.create_graph(process_id="p")
        graphs.add_node(graph.graph_id, node_id="test", node_type=GraphNodeType.DETERMINISTIC_OPERATION, max_attempts=2, operation_name="pytest")
        graphs.start_node(graph.graph_id, "test")
        graphs.fail_node(graph.graph_id, "test")
        assert graphs.retry_node(graph.graph_id, "test") is True
        graphs.start_node(graph.graph_id, "test")
        graphs.fail_node(graph.graph_id, "test")
        assert graphs.retry_node(graph.graph_id, "test") is False
        assert graphs.get_graph(graph.graph_id).nodes[0].status is GraphNodeStatus.FAILED
    finally:
        storage.stop()


def test_stalled_cycle_detects_repeated_failure_reason(tmp_path: Path):
    storage = Storage(tmp_path / "vesper.db")
    storage.migrate()
    storage.start()
    graphs = ExecutionGraphStore(storage)
    try:
        graph = graphs.create_graph(process_id="p")
        graphs.add_node(graph.graph_id, node_id="x", node_type=GraphNodeType.LANE, max_attempts=4)
        graphs.start_node(graph.graph_id, "x")
        graphs.fail_node(graph.graph_id, "x")
        graphs.retry_node(graph.graph_id, "x", reason="same failure")
        graphs.start_node(graph.graph_id, "x")
        graphs.fail_node(graph.graph_id, "x")
        assert graphs.is_stalled(graph.graph_id, "x", failure_reason="same failure", threshold=2)
    finally:
        storage.stop()


def test_retry_respects_attempt_bound(tmp_path: Path):
    storage = Storage(tmp_path / "vesper.db")
    storage.migrate()
    storage.start()
    try:
        graphs = ExecutionGraphStore(storage)
        graph = graphs.create_graph(process_id="p")
        with pytest.raises(GraphValidationError):
            graphs.add_node(graph.graph_id, node_id="test", node_type=GraphNodeType.LANE, max_attempts=0)
    finally:
        storage.stop()


def test_loop_key_is_explicit(tmp_path: Path):
    storage = Storage(tmp_path / "vesper.db")
    storage.migrate()
    storage.start()
    try:
        graphs = ExecutionGraphStore(storage)
        graph = graphs.create_graph(process_id="p")
        with pytest.raises(GraphValidationError):
            graphs.add_node(graph.graph_id, node_id="diagnose", node_type=GraphNodeType.LANE, max_attempts=2, loop_key="")
    finally:
        storage.stop()
    