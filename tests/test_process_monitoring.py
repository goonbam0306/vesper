from vesper.process_policy import ProcessMonitor


def test_monitoring_is_bounded_by_cadence_and_budget():
    monitor = ProcessMonitor(cadence_seconds=30, max_checks=2)
    assert monitor.check(now=0, condition=lambda: True) is True
    assert monitor.check(now=10, condition=lambda: False) is None
    assert monitor.check(now=30, condition=lambda: False) is False
    assert monitor.check(now=60, condition=lambda: True) is None