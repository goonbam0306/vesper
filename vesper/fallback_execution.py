"""Durable, chain-of-thought-free records for fallback execution."""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from .storage import Storage


@dataclass(frozen=True)
class FallbackExecutionRecord:
    fallback_execution_id: str
    process_id: str
    inferred_function_label: str
    cognitive_operations: tuple[str, ...]
    normalized_input_shape: dict[str, Any]
    normalized_output_shape: dict[str, Any]
    normalized_context_shape: dict[str, Any]
    tool_profile: tuple[str, ...]
    evaluation_dimensions: tuple[str, ...]
    permission_shape: tuple[str, ...]
    disposition: str
    work_unit_ref: str | None = None
    domain_tags: tuple[str, ...] = ()
    selected_model_route: str | None = None
    attempt_count: int = 1
    verification_ref: str | None = None
    latency_ms: float | None = None
    cost: dict[str, Any] | None = None
    artifact_refs: tuple[str, ...] = ()
    semantic_metadata: dict[str, Any] | None = None
    created_at: str = ""

    @classmethod
    def create(cls, process_id: str, *, inferred_function_label: str, disposition: str, **kwargs: Any) -> "FallbackExecutionRecord":
        return cls(
            fallback_execution_id=str(uuid.uuid4()),
            process_id=process_id,
            inferred_function_label=inferred_function_label,
            disposition=disposition,
            created_at=datetime.now(timezone.utc).isoformat(),
            **kwargs,
        )


class FallbackExecutionStore:
    def __init__(self, storage: Storage) -> None:
        self.storage = storage

    def save(self, record: FallbackExecutionRecord) -> FallbackExecutionRecord:
        if not record.process_id or not record.inferred_function_label.strip():
            raise ValueError("process_id and inferred_function_label are required")
        payload = asdict(record)
        payload["created_at"] = record.created_at or datetime.now(timezone.utc).isoformat()
        json_fields = {
            "domain_tags": record.domain_tags,
            "cognitive_operations": record.cognitive_operations,
            "normalized_input_shape": record.normalized_input_shape,
            "normalized_output_shape": record.normalized_output_shape,
            "normalized_context_shape": record.normalized_context_shape,
            "tool_profile": record.tool_profile,
            "evaluation_dimensions": record.evaluation_dimensions,
            "permission_shape": record.permission_shape,
            "cost": record.cost or {},
            "artifact_refs": record.artifact_refs,
            "semantic_metadata": record.semantic_metadata or {},
        }
        for key, value in json_fields.items():
            payload[key] = json.dumps(value, sort_keys=True, separators=(",", ":"))
        self.storage.write(lambda conn: conn.execute(
            """INSERT OR REPLACE INTO fallback_execution_records(
            fallback_execution_id, process_id, work_unit_ref, created_at,
            inferred_function_label, domain_tags_json, cognitive_operations_json,
            normalized_input_shape_json, normalized_output_shape_json, normalized_context_shape_json,
            tool_profile_json, evaluation_dimensions_json, permission_shape_json,
            selected_model_route, attempt_count, disposition, verification_ref, latency_ms, cost_json,
            artifact_refs_json, semantic_metadata_json
            ) VALUES (:fallback_execution_id, :process_id, :work_unit_ref, :created_at,
            :inferred_function_label, :domain_tags, :cognitive_operations,
            :normalized_input_shape, :normalized_output_shape, :normalized_context_shape,
            :tool_profile, :evaluation_dimensions, :permission_shape,
            :selected_model_route, :attempt_count, :disposition, :verification_ref, :latency_ms, :cost,
            :artifact_refs, :semantic_metadata)""", payload))
        return self.get(record.fallback_execution_id)

    def get(self, fallback_execution_id: str) -> FallbackExecutionRecord:
        row = self.storage.connect().execute(
            "SELECT * FROM fallback_execution_records WHERE fallback_execution_id = ?",
            (fallback_execution_id,),
        ).fetchone()
        if row is None:
            raise KeyError(fallback_execution_id)
        return self._from_row(row)

    def list_for_process(self, process_id: str) -> tuple[FallbackExecutionRecord, ...]:
        rows = self.storage.connect().execute(
            "SELECT * FROM fallback_execution_records WHERE process_id = ? ORDER BY created_at, fallback_execution_id",
            (process_id,),
        ).fetchall()
        return tuple(self._from_row(row) for row in rows)

    @staticmethod
    def _from_row(row: Any) -> FallbackExecutionRecord:
        data = dict(row)
        for target, source in (
            ("domain_tags", "domain_tags_json"), ("cognitive_operations", "cognitive_operations_json"),
            ("normalized_input_shape", "normalized_input_shape_json"), ("normalized_output_shape", "normalized_output_shape_json"),
            ("normalized_context_shape", "normalized_context_shape_json"), ("tool_profile", "tool_profile_json"),
            ("evaluation_dimensions", "evaluation_dimensions_json"), ("permission_shape", "permission_shape_json"),
            ("cost", "cost_json"), ("artifact_refs", "artifact_refs_json"), ("semantic_metadata", "semantic_metadata_json"),
        ):
            data[target] = json.loads(data.pop(source))
        data["domain_tags"] = tuple(data["domain_tags"])
        data["cognitive_operations"] = tuple(data["cognitive_operations"])
        data["tool_profile"] = tuple(data["tool_profile"])
        data["evaluation_dimensions"] = tuple(data["evaluation_dimensions"])
        data["permission_shape"] = tuple(data["permission_shape"])
        data["artifact_refs"] = tuple(data["artifact_refs"])
        return FallbackExecutionRecord(**data)


__all__ = ["FallbackExecutionRecord", "FallbackExecutionStore"]
