from vesper.process_policy import ProcessPolicy


def test_policy_exposes_approval_boundaries():
    policy = ProcessPolicy("p1", approval_boundaries=("external_write",))
    assert policy.requires_approval("external_write") is True
    assert policy.requires_approval("local_read") is False