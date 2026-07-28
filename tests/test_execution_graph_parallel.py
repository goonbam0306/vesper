from pathlib import Path

from vesper.execution_graph import ExecutionGraphStore, GraphNodeType
from vesper.storage import Storage


def test_independent_nodes_can_start_in_parallel(tmp_path: Path):
    storage = Storage(tmp_path / "vesper.db")
    storage.migrate()
    storage.start()
    try:
        graphs = ExecutionGraphStore(storage)
        graph = graphs.create_graph(process_id="p")
        graphs.add_node(graph.graph_id, node_id="a", node_type=GraphNodeType.LANE)
        graphs.add_node(graph.graph_id, node_id="b", node_type=GraphNodeType.LANE)
        assert graphs.can_start(graph.graph_id, "a")
        assert graphs.can_start(graph.graph_id, "b")
        graphs.start_node(graph.graph_id, "a")
        graphs.start_node(graph.graph_id, "b")
    finally:
        storage.stop()


def test_join_waits_for_all_required_predecessors(tmp_path: Path):
    storage = Storage(tmp_path / "vesper.db")
    storage.migrate()
    storage.start()
    try:
        graphs = ExecutionGraphStore(storage)
        graph = graphs.create_graph(process_id="p")
        graphs.add_node(graph.graph_id, node_id="a", node_type=GraphNodeType.LANE)
        graphs.add_node(graph.graph_id, node_id="b", node_type=GraphNodeType.LANE)
        graphs.add_node(graph.graph_id, node_id="join", node_type=GraphNodeType.DETERMINISTIC_OPERATION, dependencies=("a", "b"), operation_name="build")
        graphs.start_node(graph.graph_id, "a")
        graphs.complete_node(graph.graph_id, "a")
        assert not graphs.can_start(graph.graph_id, "join")
        graphs.start_node(graph.graph_id, "b")
        graphs.complete_node(graph.graph_id, "b")
        assert graphs.can_start(graph.graph_id, "join")
    finally:
        storage.stop()
    


def test_failed_predecessor_is_not_successful_dependency(tmp_path: Path):
    storage = Storage(tmp_path / "vesper.db")
    storage.migrate()
    storage.start()
    try:
        graphs = ExecutionGraphStore(storage)
        graph = graphs.create_graph(process_id="p")
        graphs.add_node(graph.graph_id, node_id="a", node_type=GraphNodeType.LANE)
        graphs.add_node(graph.graph_id, node_id="b", node_type=GraphNodeType.LANE, dependencies=("a",))
        graphs.start_node(graph.graph_id, "a")
        graphs.fail_node(graph.graph_id, "a")
        assert not graphs.can_start(graph.graph_id, "b")
    finally:
        storage.stop()
    


def test_graph_parallel_state_survives_restart(tmp_path: Path):
    storage = Storage(tmp_path / "vesper.db")
    storage.migrate()
    storage.start()
    graphs = ExecutionGraphStore(storage)
    graph = graphs.create_graph(process_id="p")
    graphs.add_node(graph.graph_id, node_id="a", node_type=GraphNodeType.LANE)
    graphs.add_node(graph.graph_id, node_id="b", node_type=GraphNodeType.LANE)
    graphs.start_node(graph.graph_id, "a")
    storage.stop()
    storage.start()
    try:
        restored = ExecutionGraphStore(storage).get_graph(graph.graph_id)
        assert restored.nodes[0].status.value == "RUNNING"
    finally:
        storage.stop()
    
    