from pathlib import Path

import pytest

from vesper.execution_graph import ExecutionGraphStore, GraphNodeType, GraphValidationError
from vesper.storage import Storage


def test_deterministic_operation_has_kernel_operation_name(tmp_path: Path):
    storage = Storage(tmp_path / "vesper.db")
    storage.migrate()
    storage.start()
    try:
        graphs = ExecutionGraphStore(storage)
        graph = graphs.create_graph(process_id="p")
        node = graphs.add_node(graph.graph_id, node_id="test", node_type=GraphNodeType.DETERMINISTIC_OPERATION, operation_name="pytest")
        assert node.operation_name == "pytest"
    finally:
        storage.stop()


def test_operation_name_is_not_allowed_on_lane_node(tmp_path: Path):
    storage = Storage(tmp_path / "vesper.db")
    storage.migrate()
    storage.start()
    try:
        graphs = ExecutionGraphStore(storage)
        graph = graphs.create_graph(process_id="p")
        with pytest.raises(GraphValidationError):
            graphs.add_node(graph.graph_id, node_id="lane", node_type=GraphNodeType.LANE, operation_name="pytest")
    finally:
        storage.stop()


def test_unknown_kernel_operation_is_rejected(tmp_path: Path):
    storage = Storage(tmp_path / "vesper.db")
    storage.migrate()
    storage.start()
    try:
        graphs = ExecutionGraphStore(storage)
        graph = graphs.create_graph(process_id="p")
        with pytest.raises(GraphValidationError):
            graphs.add_node(graph.graph_id, node_id="op", node_type=GraphNodeType.DETERMINISTIC_OPERATION, operation_name="arbitrary_shell")
    finally:
        storage.stop()
    


def test_graph_does_not_materialize_test_lane_for_operation(tmp_path: Path):
    storage = Storage(tmp_path / "vesper.db")
    storage.migrate()
    storage.start()
    try:
        graphs = ExecutionGraphStore(storage)
        graph = graphs.create_graph(process_id="p")
        node = graphs.add_node(graph.graph_id, node_id="lint", node_type=GraphNodeType.DETERMINISTIC_OPERATION, operation_name="lint")
        assert node.node_type is GraphNodeType.DETERMINISTIC_OPERATION
    finally:
        storage.stop()
    
    