from vesper.process_policy import ProcessBudget


def test_budget_consumption_and_replenishment_are_bounded():
    budget = ProcessBudget(tokens=100, seconds=60)
    assert budget.consume(tokens=40, seconds=10) is True
    assert budget.consume(tokens=61, seconds=1) is False
    budget.replenish(tokens=20, seconds=10)
    assert budget.consume(tokens=60, seconds=40) is True