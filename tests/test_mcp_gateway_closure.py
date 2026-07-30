from pathlib import Path

import pytest

from vesper.api import Runtime
from vesper.connections import CapabilityState, ConnectionError
from vesper.mcp_gateway import LocalCustomMCPSandbox, MCPGateway
from vesper.storage import Storage


def gateway(tmp_path: Path):
    storage = Storage(tmp_path / "vesper.sqlite3")
    storage.migrate(); storage.start()
    runtime = Runtime(tmp_path)
    runtime.storage = storage
    from vesper.connections import ConnectionStore
    connections = ConnectionStore(storage)
    return storage, connections, MCPGateway(storage, connections)


def activate(connections, capability_id: str) -> None:
    connections.set_capability_state(capability_id, CapabilityState.ELIGIBLE)
    connections.set_capability_state(capability_id, CapabilityState.EXPOSED)


def test_mcp_read_vertical_is_provenance_bearing_and_untrusted(tmp_path: Path):
    storage, connections, mcp = gateway(tmp_path)
    mcp.register_local_server(server_id="sandbox", display_name="Sandbox", transport=LocalCustomMCPSandbox())
    capabilities = mcp.discover("sandbox")
    read = next(item for item in capabilities if item["name"] == "sandbox.read")
    activate(connections, read["capability_id"])
    observation = mcp.read(server_id="sandbox", capability_id=read["capability_id"], arguments={"key": "seed"})
    assert observation["authority"] == "EVIDENCE_ONLY"
    assert observation["instruction_trust"] == "UNTRUSTED_EXTERNAL"
    assert observation["content"]["source"] == "local-custom-sandbox"
    assert mcp.overview()["observations"][0]["server_id"] == "sandbox"


def test_mcp_write_requires_approval_is_idempotent_and_has_kernel_receipt(tmp_path: Path):
    storage, connections, mcp = gateway(tmp_path)
    mcp.register_local_server(server_id="sandbox", display_name="Sandbox", transport=LocalCustomMCPSandbox())
    write = next(item for item in mcp.discover("sandbox") if item["name"] == "sandbox.write")
    effect = mcp.propose_write(server_id="sandbox", capability_id=write["capability_id"], process_id="process-1", idempotency_key="write-1")
    assert effect["status"] == "PENDING_APPROVAL"
    duplicate = mcp.propose_write(server_id="sandbox", capability_id=write["capability_id"], process_id="process-1", idempotency_key="write-1")
    assert duplicate["effect_id"] == effect["effect_id"]
    confirmed = mcp.approve_and_execute(effect_id=effect["effect_id"], approved=True, arguments={"key": "x", "value": "safe"})
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["receipt"]["authority"] == "VESPER_KERNEL"


def test_mcp_ambiguous_write_is_not_replayed(tmp_path: Path):
    storage, connections, mcp = gateway(tmp_path)
    sandbox = LocalCustomMCPSandbox(); sandbox.failure = "ambiguous"
    mcp.register_local_server(server_id="sandbox", display_name="Sandbox", transport=sandbox)
    write = next(item for item in mcp.discover("sandbox") if item["name"] == "sandbox.write")
    effect = mcp.propose_write(server_id="sandbox", capability_id=write["capability_id"], process_id="process-1", idempotency_key="uncertain-1")
    ambiguous = mcp.approve_and_execute(effect_id=effect["effect_id"], approved=True, arguments={"key": "x", "value": "may-have-written"})
    assert ambiguous["status"] == "AMBIGUOUS"
    again = mcp.approve_and_execute(effect_id=effect["effect_id"], approved=True, arguments={"key": "x", "value": "must-not-replay"})
    assert again["status"] == "AMBIGUOUS"
    assert sandbox.items["x"]["value"] == "may-have-written"


def test_schema_change_requires_new_registered_review_and_transport_failure_is_visible(tmp_path: Path):
    storage, connections, mcp = gateway(tmp_path)
    sandbox = LocalCustomMCPSandbox()
    mcp.register_local_server(server_id="sandbox", display_name="Sandbox", transport=sandbox)
    initial = mcp.discover("sandbox")
    sandbox.schema_generation = 2
    changed = mcp.discover("sandbox")
    read = next(item for item in changed if item["name"] == "sandbox.read")
    assert read["schema_review_required"] is True
    assert read["state"] == "REGISTERED"
    sandbox.failure = "unavailable"
    with pytest.raises(ConnectionError) as exc:
        mcp.discover("sandbox")
    assert exc.value.code == "MCP_TIMEOUT"
    assert mcp.server("sandbox")["health"] == "OFFLINE"
