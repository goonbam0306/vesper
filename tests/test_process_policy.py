import pytest

from vesper.process_policy import ProcessPolicy, ProcessPolicyStore
from vesper.storage import Storage


def test_process_policy_is_durable_and_bounds_graph_growth(tmp_path):
    storage = Storage(tmp_path / "policy.db")
    storage.migrate()
    storage.start()
    storage.write(lambda c: c.execute("INSERT INTO processes(process_id,status,origin,created_at,updated_at) VALUES('p1','RUNNING','test','now','now')"))
    store = ProcessPolicyStore(storage)
    policy = ProcessPolicy(process_id="p1", max_graph_nodes=12, max_expansion_depth=3,
                           max_lane_invocations=8, max_replan_count=2, retry_budget=4,
                           deadline_at="2099-01-01T00:00:00+00:00", cost_token_budget=1000)
    store.create(policy)
    restored = store.get("p1")
    assert restored == policy
    assert restored.allows_graph(nodes=12, depth=3, lane_invocations=8, replans=2, retries=4)
    assert not restored.allows_graph(nodes=13, depth=3, lane_invocations=8, replans=2, retries=4)
    with pytest.raises(ValueError):
        ProcessPolicy(process_id="p2", max_graph_nodes=0)