from pathlib import Path

import pytest

from vesper.execution_graph import ExecutionGraphStore, GraphNodeType, GraphValidationError
from vesper.storage import Storage


def test_conditional_edge_is_durable(tmp_path: Path):
    storage = Storage(tmp_path / "vesper.db")
    storage.migrate()
    storage.start()
    try:
        graphs = ExecutionGraphStore(storage)
        graph = graphs.create_graph(process_id="p")
        graphs.add_node(graph.graph_id, node_id="verify", node_type=GraphNodeType.DETERMINISTIC_OPERATION, operation_name="pytest")
        graphs.add_node(graph.graph_id, node_id="compose", node_type=GraphNodeType.LANE)
        graphs.add_edge(graph.graph_id, "verify", "compose", condition={"result": "PASS"})
        edge = graphs.get_edges(graph.graph_id)[0]
        assert edge.condition == {"result": "PASS"}
    finally:
        storage.stop()


def test_edge_requires_existing_nodes(tmp_path: Path):
    storage = Storage(tmp_path / "vesper.db")
    storage.migrate()
    storage.start()
    try:
        graphs = ExecutionGraphStore(storage)
        graph = graphs.create_graph(process_id="p")
        with pytest.raises(GraphValidationError):
            graphs.add_edge(graph.graph_id, "missing", "also-missing", condition={"result": "PASS"})
    finally:
        storage.stop()


def test_edge_condition_is_deterministic_and_typed(tmp_path: Path):
    storage = Storage(tmp_path / "vesper.db")
    storage.migrate()
    storage.start()
    try:
        graphs = ExecutionGraphStore(storage)
        graph = graphs.create_graph(process_id="p")
        graphs.add_node(graph.graph_id, node_id="a", node_type=GraphNodeType.LANE)
        graphs.add_node(graph.graph_id, node_id="b", node_type=GraphNodeType.LANE)
        with pytest.raises(GraphValidationError):
            graphs.add_edge(graph.graph_id, "a", "b", condition=["PASS"])
    finally:
        storage.stop()
    