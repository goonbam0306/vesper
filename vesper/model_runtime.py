"""Bounded model route registry and weakest-sufficient routing."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from .storage import Storage


@dataclass(frozen=True)
class CognitiveRequest:
    capabilities: frozenset[str] = frozenset({"text"})
    privacy: str = "local_preferred"
    reliability_floor: float = 0.0
    max_cost: float | None = None
    max_latency_ms: float | None = None


@dataclass(frozen=True)
class ModelRoute:
    route_id: str
    model_id: str
    provider: str
    capabilities: frozenset[str]
    privacy: str
    reliability: float
    cost: float
    latency_ms: float
    enabled: bool
    credential_ref: str | None


class NoEligibleRoute(RuntimeError):
    pass


class ModelRegistry:
    def __init__(self, storage: Storage):
        self.storage = storage

    @staticmethod
    def _row(row: sqlite3.Row) -> ModelRoute:
        return ModelRoute(row["route_id"], row["model_id"], row["provider"], frozenset(json.loads(row["capabilities_json"])), row["privacy"], row["reliability"], row["cost"], row["latency_ms"], bool(row["enabled"]), row["credential_ref"])

    def register(self, route: ModelRoute) -> ModelRoute:
        def op(c: sqlite3.Connection) -> ModelRoute:
            c.execute("INSERT OR REPLACE INTO model_routes VALUES (?,?,?,?,?,?,?,?,?,?)", (route.route_id, route.model_id, route.provider, json.dumps(sorted(route.capabilities)), route.privacy, route.reliability, route.cost, route.latency_ms, int(route.enabled), route.credential_ref))
            return route
        return self.storage.write(op)

    def eligible(self, request: CognitiveRequest) -> list[ModelRoute]:
        def read(c: sqlite3.Connection) -> list[ModelRoute]:
            routes = [self._row(row) for row in c.execute("SELECT * FROM model_routes WHERE enabled=1").fetchall()]
            return [route for route in routes if request.capabilities <= route.capabilities and route.reliability >= request.reliability_floor and (request.max_cost is None or route.cost <= request.max_cost) and (request.max_latency_ms is None or route.latency_ms <= request.max_latency_ms)]
        return self.storage.write(read)

    def route(self, request: CognitiveRequest) -> ModelRoute:
        routes = self.eligible(request)
        if not routes:
            raise NoEligibleRoute("no route satisfies request")
        routes.sort(key=lambda r: (0 if request.privacy == "local_preferred" and r.privacy == "local" else 1, r.reliability, r.cost, r.latency_ms))
        return routes[0]
