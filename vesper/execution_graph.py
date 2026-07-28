"""Durable execution graph model backed by the canonical Storage writer."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from .storage import Storage
from .adaptive_execution import LaneOutcomeValidator, WorkExpansionProposal


class GraphValidationError(ValueError):
    """Invalid graph or node contract."""


class GraphNodeType(StrEnum):
    LANE = "LANE"
    DETERMINISTIC_OPERATION = "DETERMINISTIC_OPERATION"
    APPROVAL_WAIT = "APPROVAL_WAIT"
    USER_INPUT_WAIT = "USER_INPUT_WAIT"


class GraphNodeStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class GraphNode:
    graph_id: str
    node_id: str
    node_type: GraphNodeType
    status: GraphNodeStatus
    dependencies: tuple[str, ...]
    parent_node_id: str | None
    created_at: str
    updated_at: str
    max_attempts: int = 1
    attempt_count: int = 0
    loop_key: str | None = None
    operation_name: str | None = None


@dataclass(frozen=True)
class GraphWait:
    graph_id: str
    node_id: str
    wait_key: str
    resumed: bool
    payload: dict[str, Any] | None
    created_at: str
    resumed_at: str | None


@dataclass(frozen=True)
class GraphRevision:
    graph_id: str
    revision_id: str
    status: str
    reason: str
    requested_by: str
    approved_by: str | None
    created_at: str
    decided_at: str | None
    target_node_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class GraphEdge:
    graph_id: str
    from_node_id: str
    to_node_id: str
    condition: dict[str, Any] | None


@dataclass(frozen=True)
class ExecutionGraph:
    graph_id: str
    process_id: str
    created_at: str
    updated_at: str
    nodes: tuple[GraphNode, ...]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _node(row: Any) -> GraphNode:
    return GraphNode(
        graph_id=row["graph_id"], node_id=row["node_id"],
        node_type=GraphNodeType(row["node_type"]),
        status=GraphNodeStatus(row["status"]),
        dependencies=tuple(json.loads(row["dependencies_json"])),
        parent_node_id=row["parent_node_id"],
        created_at=row["created_at"], updated_at=row["updated_at"],
        max_attempts=row["max_attempts"] if "max_attempts" in row.keys() else 1,
        attempt_count=row["attempt_count"] if "attempt_count" in row.keys() else 0,
        loop_key=row["loop_key"] if "loop_key" in row.keys() else None,
        operation_name=row["operation_name"] if "operation_name" in row.keys() else None,
    )


class ExecutionGraphStore:
    def __init__(self, storage: Storage) -> None:
        if not isinstance(storage, Storage):
            raise TypeError("ExecutionGraphStore requires canonical Storage")
        self.storage = storage

    def create_graph(self, *, process_id: str, graph_id: str | None = None) -> ExecutionGraph:
        if not process_id:
            raise GraphValidationError("process_id is required")
        graph_id = graph_id or f"graph_{uuid.uuid4().hex}"
        timestamp = _now()
        self.storage.write(lambda conn: conn.execute(
            "INSERT INTO execution_graphs(graph_id, process_id, created_at, updated_at) VALUES (?,?,?,?)",
            (graph_id, process_id, timestamp, timestamp),
        ))
        return ExecutionGraph(graph_id, process_id, timestamp, timestamp, ())

    def add_node(
        self,
        graph_id: str,
        *,
        node_id: str,
        node_type: GraphNodeType | str,
        dependencies: tuple[str, ...] = (),
        parent_node_id: str | None = None,
        max_attempts: int = 1,
        loop_key: str | None = None,
        operation_name: str | None = None,
    ) -> GraphNode:
        try:
            normalized_type = GraphNodeType(node_type)
        except ValueError as exc:
            raise GraphValidationError(f"unsupported graph node type: {node_type}") from exc
        if not node_id:
            raise GraphValidationError("node_id is required")
        if not isinstance(max_attempts, int) or max_attempts < 1:
            raise GraphValidationError("max_attempts must be positive")
        if loop_key is not None and not loop_key:
            raise GraphValidationError("loop_key cannot be empty")
        allowed_operations = {"pytest", "build", "lint", "schema_validation", "approved_file_apply"}
        if normalized_type is GraphNodeType.DETERMINISTIC_OPERATION:
            if operation_name not in allowed_operations:
                raise GraphValidationError("unknown or missing Kernel operation")
        elif operation_name is not None:
            raise GraphValidationError("operation_name is only valid for deterministic operation nodes")
        timestamp = _now()

        def insert(conn):
            graph = conn.execute("SELECT 1 FROM execution_graphs WHERE graph_id=?", (graph_id,)).fetchone()
            if graph is None:
                raise GraphValidationError(f"unknown graph: {graph_id}")
            for dependency in dependencies:
                if conn.execute("SELECT 1 FROM execution_graph_nodes WHERE graph_id=? AND node_id=?", (graph_id, dependency)).fetchone() is None:
                    raise GraphValidationError(f"unknown dependency: {dependency}")
            conn.execute(
                "INSERT INTO execution_graph_nodes(graph_id,node_id,node_type,status,dependencies_json,parent_node_id,created_at,updated_at,max_attempts,attempt_count,loop_key,operation_name) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (graph_id, node_id, normalized_type.value, GraphNodeStatus.PENDING.value, json.dumps(list(dependencies)), parent_node_id, timestamp, timestamp, max_attempts, 0, loop_key, operation_name),
            )

        self.storage.write(insert)
        return GraphNode(graph_id, node_id, normalized_type, GraphNodeStatus.PENDING, tuple(dependencies), parent_node_id, timestamp, timestamp, max_attempts, 0, loop_key, operation_name)

    def get_graph(self, graph_id: str) -> ExecutionGraph:
        connection = self.storage.connect()
        try:
            row = connection.execute("SELECT * FROM execution_graphs WHERE graph_id=?", (graph_id,)).fetchone()
            if row is None:
                raise GraphValidationError(f"unknown graph: {graph_id}")
            nodes = tuple(_node(item) for item in connection.execute("SELECT * FROM execution_graph_nodes WHERE graph_id=? ORDER BY created_at,node_id", (graph_id,)))
            return ExecutionGraph(row["graph_id"], row["process_id"], row["created_at"], row["updated_at"], nodes)
        finally:
            connection.close()

    def can_start(self, graph_id: str, node_id: str) -> bool:
        graph = self.get_graph(graph_id)
        node = next((item for item in graph.nodes if item.node_id == node_id), None)
        if node is None:
            raise GraphValidationError(f"unknown node: {node_id}")
        return node.status == GraphNodeStatus.PENDING and all(
            next(item for item in graph.nodes if item.node_id == dependency).status == GraphNodeStatus.COMPLETED
            for dependency in node.dependencies
        )

    def add_edge(self, graph_id: str, from_node_id: str, to_node_id: str, *, condition: dict[str, Any] | None = None) -> GraphEdge:
        if condition is not None and not isinstance(condition, dict):
            raise GraphValidationError("edge condition must be an object")
        def insert(conn):
            for node_id in (from_node_id, to_node_id):
                if conn.execute("SELECT 1 FROM execution_graph_nodes WHERE graph_id=? AND node_id=?", (graph_id, node_id)).fetchone() is None:
                    raise GraphValidationError(f"unknown node: {node_id}")
            conn.execute("INSERT INTO execution_graph_edges(graph_id,from_node_id,to_node_id,condition_json) VALUES (?,?,?,?)", (graph_id, from_node_id, to_node_id, json.dumps(condition, sort_keys=True) if condition is not None else None))
        self.storage.write(insert)
        return GraphEdge(graph_id, from_node_id, to_node_id, condition)

    def get_edges(self, graph_id: str) -> tuple[GraphEdge, ...]:
        connection = self.storage.connect()
        try:
            return tuple(GraphEdge(row["graph_id"], row["from_node_id"], row["to_node_id"], json.loads(row["condition_json"]) if row["condition_json"] else None) for row in connection.execute("SELECT * FROM execution_graph_edges WHERE graph_id=? ORDER BY from_node_id,to_node_id", (graph_id,)))
        finally:
            connection.close()

    def complete_node(self, graph_id: str, node_id: str) -> None:
        timestamp = _now()
        self.storage.write(lambda conn: conn.execute(
            "UPDATE execution_graph_nodes SET status=?, updated_at=? WHERE graph_id=? AND node_id=?",
            (GraphNodeStatus.COMPLETED.value, timestamp, graph_id, node_id),
        ))
        self.storage.write(lambda conn: conn.execute(
            "UPDATE execution_graphs SET updated_at=? WHERE graph_id=?", (timestamp, graph_id)
        ))

    def start_node(self, graph_id: str, node_id: str) -> None:
        if not self.can_start(graph_id, node_id):
            raise GraphValidationError(f"node cannot start: {node_id}")
        timestamp = _now()
        self.storage.write(lambda conn: conn.execute(
            "UPDATE execution_graph_nodes SET status=?, attempt_count=attempt_count+1, updated_at=? WHERE graph_id=? AND node_id=?",
            (GraphNodeStatus.RUNNING.value, timestamp, graph_id, node_id),
        ))

    def retry_node(self, graph_id: str, node_id: str, *, reason: str | None = None) -> bool:
        graph = self.get_graph(graph_id)
        node = next((item for item in graph.nodes if item.node_id == node_id), None)
        if node is None:
            raise GraphValidationError(f"unknown node: {node_id}")
        if node.status is not GraphNodeStatus.FAILED:
            raise GraphValidationError("only failed nodes can be retried")
        if node.attempt_count >= node.max_attempts:
            return False
        timestamp = _now()
        def retry(conn):
            conn.execute("INSERT INTO execution_graph_retries(graph_id,node_id,attempt,reason,created_at) VALUES (?,?,?,?,?)", (graph_id, node_id, node.attempt_count, reason, timestamp))
            conn.execute("UPDATE execution_graph_nodes SET status=?, updated_at=? WHERE graph_id=? AND node_id=?", (GraphNodeStatus.PENDING.value, timestamp, graph_id, node_id))
        self.storage.write(retry)
        return True

    def fail_node(self, graph_id: str, node_id: str) -> None:
        timestamp = _now()
        self.storage.write(lambda conn: conn.execute(
            "UPDATE execution_graph_nodes SET status=?, updated_at=? WHERE graph_id=? AND node_id=?",
            (GraphNodeStatus.FAILED.value, timestamp, graph_id, node_id),
        ))

    def cancel_node(self, graph_id: str, node_id: str) -> None:
        timestamp = _now()
        self.storage.write(lambda conn: conn.execute(
            "UPDATE execution_graph_nodes SET status=?, updated_at=? WHERE graph_id=? AND node_id=?",
            (GraphNodeStatus.CANCELLED.value, timestamp, graph_id, node_id),
        ))

    def wait_node(self, graph_id: str, node_id: str, *, wait_key: str, blocked: bool = False) -> GraphWait:
        if not wait_key:
            raise GraphValidationError("wait_key is required")
        graph = self.get_graph(graph_id)
        node = next((item for item in graph.nodes if item.node_id == node_id), None)
        if node is None or (not blocked and node.node_type not in {GraphNodeType.APPROVAL_WAIT, GraphNodeType.USER_INPUT_WAIT}):
            raise GraphValidationError("wait_node requires an approval, user-input, or explicitly blocked node")
        timestamp = _now()
        self.storage.write(lambda conn: conn.execute(
            "INSERT INTO execution_graph_waits(graph_id,node_id,wait_key,created_at) VALUES (?,?,?,?)",
            (graph_id, node_id, wait_key, timestamp),
        ))
        return GraphWait(graph_id, node_id, wait_key, False, None, timestamp, None)

    def get_wait(self, graph_id: str, node_id: str) -> GraphWait:
        connection = self.storage.connect()
        try:
            row = connection.execute("SELECT * FROM execution_graph_waits WHERE graph_id=? AND node_id=?", (graph_id, node_id)).fetchone()
            if row is None:
                raise GraphValidationError("wait does not exist")
            return GraphWait(row["graph_id"], row["node_id"], row["wait_key"], bool(row["resumed"]), json.loads(row["payload_json"]) if row["payload_json"] else None, row["created_at"], row["resumed_at"])
        finally:
            connection.close()

    def resume_wait(self, graph_id: str, node_id: str, *, payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            raise GraphValidationError("wait payload must be an object")
        wait = self.get_wait(graph_id, node_id)
        if wait.resumed:
            raise GraphValidationError("wait is already resumed")
        timestamp = _now()
        self.storage.write(lambda conn: conn.execute(
            "UPDATE execution_graph_waits SET resumed=1,payload_json=?,resumed_at=? WHERE graph_id=? AND node_id=? AND resumed=0",
            (json.dumps(payload, sort_keys=True), timestamp, graph_id, node_id),
        ))

    def request_revision(self, graph_id: str, *, reason: str, requested_by: str, target_node_ids: tuple[str, ...] = ()) -> GraphRevision:
        if not reason or not requested_by or any(not node_id for node_id in target_node_ids):
            raise GraphValidationError("revision reason, requester, and valid targets are required")
        revision_id = f"revision_{uuid.uuid4().hex}"
        timestamp = _now()
        targets_json = json.dumps(list(target_node_ids), sort_keys=True)
        self.storage.write(lambda conn: conn.execute(
            "INSERT INTO execution_graph_revisions(graph_id,revision_id,status,reason,requested_by,created_at,target_node_ids_json) VALUES (?,?,?,?,?,?,?)",
            (graph_id, revision_id, "REQUESTED", reason, requested_by, timestamp, targets_json),
        ))
        return GraphRevision(graph_id, revision_id, "REQUESTED", reason, requested_by, None, timestamp, None, tuple(target_node_ids))

    def approve_revision(self, graph_id: str, revision_id: str, *, approved_by: str) -> None:
        if not approved_by:
            raise GraphValidationError("approver is required")
        timestamp = _now()
        def approve(conn):
            row = conn.execute("SELECT status FROM execution_graph_revisions WHERE graph_id=? AND revision_id=?", (graph_id, revision_id)).fetchone()
            if row is None:
                raise GraphValidationError("revision does not exist")
            if row["status"] != "REQUESTED":
                raise GraphValidationError("revision is already decided")
            conn.execute("UPDATE execution_graph_revisions SET status='APPROVED',approved_by=?,decided_at=? WHERE graph_id=? AND revision_id=?", (approved_by, timestamp, graph_id, revision_id))
        self.storage.write(approve)

    def apply_revision(self, graph_id: str, revision_id: str) -> None:
        def apply(conn):
            row = conn.execute("SELECT status,target_node_ids_json FROM execution_graph_revisions WHERE graph_id=? AND revision_id=?", (graph_id, revision_id)).fetchone()
            if row is None or row["status"] != "APPROVED":
                raise GraphValidationError("only an approved revision can be applied")
            targets = tuple(json.loads(row["target_node_ids_json"]))
            if not targets:
                raise GraphValidationError("revision has no partial graph targets")
            existing = {item["node_id"] for item in conn.execute("SELECT node_id FROM execution_graph_nodes WHERE graph_id=?", (graph_id,))}
            if any(node_id not in existing for node_id in targets):
                raise GraphValidationError("revision target node does not exist")
            timestamp = _now()
            conn.executemany("UPDATE execution_graph_nodes SET status=?,updated_at=? WHERE graph_id=? AND node_id=? AND status != ?", [(GraphNodeStatus.PENDING.value, timestamp, graph_id, node_id, GraphNodeStatus.COMPLETED.value) for node_id in targets])
        self.storage.write(apply)

    def expand(self, graph_id: str, proposal: WorkExpansionProposal, *, available_lane_ids: set[str], max_nodes: int, max_expansion_depth: int | None = None, max_graph_nodes: int | None = None) -> tuple[GraphNode, ...]:
        try:
            LaneOutcomeValidator._validate_expansion(proposal)
        except ValueError as exc:
            raise GraphValidationError(str(exc)) from exc
        if max_nodes < 1 or len(proposal.proposed_work_units) > max_nodes:
            raise GraphValidationError("expansion exceeds process node budget")
        graph = self.get_graph(graph_id)
        if max_graph_nodes is not None and len(graph.nodes) + len(proposal.proposed_work_units) > max_graph_nodes:
            raise GraphValidationError("expansion exceeds graph node budget")
        existing = {node.node_id for node in graph.nodes}
        units = proposal.proposed_work_units
        ids = {unit.local_id for unit in units}
        if existing & ids:
            raise GraphValidationError("expansion node already exists")
        operations = {"pytest", "build", "lint", "schema_validation", "approved_file_apply"}
        for unit in units:
            if unit.function_or_lane not in available_lane_ids and unit.function_or_lane not in operations:
                raise GraphValidationError(f"lane is unavailable: {unit.function_or_lane}")
            if any(dep not in ids and dep not in existing for dep in unit.depends_on):
                raise GraphValidationError("expansion dependency is unknown")
        visiting: set[str] = set()
        visited: set[str] = set()
        by_id = {unit.local_id: unit for unit in units}
        def visit(node_id: str) -> None:
            if node_id in visiting:
                raise GraphValidationError("expansion contains a cycle")
            if node_id in visited or node_id not in by_id:
                return
            visiting.add(node_id)
            for dependency in by_id[node_id].depends_on:
                visit(dependency)
            visiting.remove(node_id)
            visited.add(node_id)
        for unit in units:
            visit(unit.local_id)
        created = []
        for unit in units:
            node_type = GraphNodeType.DETERMINISTIC_OPERATION if unit.function_or_lane in operations else GraphNodeType.LANE
            created.append(self.add_node(graph_id, node_id=unit.local_id, node_type=node_type, dependencies=unit.depends_on, operation_name=unit.function_or_lane if node_type is GraphNodeType.DETERMINISTIC_OPERATION else None, parent_node_id=proposal.parent_node_id))
        return tuple(created)

    def is_stalled(self, graph_id: str, node_id: str, *, failure_reason: str, threshold: int = 2) -> bool:
        if not failure_reason or threshold < 1:
            raise GraphValidationError("failure_reason and positive threshold are required")
        connection = self.storage.connect()
        try:
            row = connection.execute("SELECT COUNT(*) AS count FROM execution_graph_retries WHERE graph_id=? AND node_id=? AND reason=?", (graph_id, node_id, failure_reason)).fetchone()
            return int(row["count"]) + 1 >= threshold
        finally:
            connection.close()

    def recover_running_nodes(self, graph_id: str) -> tuple[str, ...]:
        timestamp = _now()
        def recover(conn):
            rows = conn.execute("SELECT node_id FROM execution_graph_nodes WHERE graph_id=? AND status=? ORDER BY node_id", (graph_id, GraphNodeStatus.RUNNING.value)).fetchall()
            node_ids = tuple(row["node_id"] for row in rows)
            if node_ids:
                conn.execute("UPDATE execution_graph_nodes SET status=?,updated_at=? WHERE graph_id=? AND status=?", (GraphNodeStatus.PENDING.value, timestamp, graph_id, GraphNodeStatus.RUNNING.value))
            return node_ids
        return self.storage.write(recover)

    def get_revisions(self, graph_id: str) -> tuple[GraphRevision, ...]:
        connection = self.storage.connect()
        try:
            return tuple(GraphRevision(row["graph_id"], row["revision_id"], row["status"], row["reason"], row["requested_by"], row["approved_by"], row["created_at"], row["decided_at"], tuple(json.loads(row["target_node_ids_json"]))) for row in connection.execute("SELECT * FROM execution_graph_revisions WHERE graph_id=? ORDER BY created_at,revision_id", (graph_id,)))
        finally:
            connection.close()
