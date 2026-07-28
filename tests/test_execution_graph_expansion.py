from pathlib import Path

import pytest

from vesper.adaptive_execution import ProposedWorkUnit, WorkExpansionProposal
from vesper.execution_graph import ExecutionGraphStore, GraphNodeType, GraphValidationError
from vesper.storage import Storage


def _store(tmp_path: Path):
    storage = Storage(tmp_path / "vesper.db")
    storage.migrate()
    storage.start()
    return storage, ExecutionGraphStore(storage)


def test_expand_materializes_bounded_local_nodes(tmp_path: Path):
    storage, graphs = _store(tmp_path)
    try:
        graph = graphs.create_graph(process_id="p")
        proposal = WorkExpansionProposal("validate", (
            ProposedWorkUnit("verify", "verify", "run verification"),
            ProposedWorkUnit("compose", "compose", "write report", ("verify",)),
        ))
        nodes = graphs.expand(graph.graph_id, proposal, available_lane_ids={"verify", "compose"}, max_nodes=3)
        assert [node.node_id for node in nodes] == ["verify", "compose"]
        assert nodes[1].dependencies == ("verify",)
    finally:
        storage.stop()


def test_expand_rejects_unknown_lane_and_cycle(tmp_path: Path):
    storage, graphs = _store(tmp_path)
    try:
        graph = graphs.create_graph(process_id="p")
        with pytest.raises(GraphValidationError):
            graphs.expand(graph.graph_id, WorkExpansionProposal("x", (ProposedWorkUnit("x", "missing", "x"),)), available_lane_ids={"verify"}, max_nodes=3)
        cyclic = WorkExpansionProposal("x", (ProposedWorkUnit("a", "verify", "a", ("b",)), ProposedWorkUnit("b", "verify", "b", ("a",))))
        with pytest.raises(GraphValidationError):
            graphs.expand(graph.graph_id, cyclic, available_lane_ids={"verify"}, max_nodes=3)
    finally:
        storage.stop()


def test_expand_budget_and_duplicate_are_rejected(tmp_path: Path):
    storage, graphs = _store(tmp_path)
    try:
        graph = graphs.create_graph(process_id="p")
        proposal = WorkExpansionProposal("x", (ProposedWorkUnit("a", "verify", "a"),))
        with pytest.raises(GraphValidationError):
            graphs.expand(graph.graph_id, proposal, available_lane_ids={"verify"}, max_nodes=0)
        graphs.expand(graph.graph_id, proposal, available_lane_ids={"verify"}, max_nodes=2)
        with pytest.raises(GraphValidationError):
            graphs.expand(graph.graph_id, proposal, available_lane_ids={"verify"}, max_nodes=2)
    finally:
        storage.stop()


def test_expansion_limits_depth_and_total_graph_size(tmp_path: Path):
    storage, graphs = _store(tmp_path)
    try:
        graph = graphs.create_graph(process_id="p")
        graphs.add_node(graph.graph_id, node_id="root", node_type=GraphNodeType.LANE)
        proposal = WorkExpansionProposal("grow", (ProposedWorkUnit("child", "lane", "child", ("root",)),))
        with pytest.raises(GraphValidationError):
            graphs.expand(graph.graph_id, proposal, available_lane_ids={"lane"}, max_nodes=1, max_expansion_depth=0, max_graph_nodes=2)
    finally:
        storage.stop()
