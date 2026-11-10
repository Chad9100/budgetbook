from budgetbook import db


def test_budget_page_shows_spent_and_remaining(post, client, category, add_tx):
    food = category("Food")
    add_tx(date="2026-10-03", amount="30", category_id=food)
    add_tx(date="2026-10-20", amount="15.50", category_id=food)
    add_tx(date="2026-10-21", kind="income", amount="5.50", category_id=food)  # refund
    add_tx(date="2026-11-01", amount="99", category_id=food)
    assert post("/budgets", {"month": "2026-10", f"budget_{food}": "100"}).status_code == 302
    body = client.get("/budgets?month=2026-10").get_data(as_text=True)
    assert 'value="100.00"' in body
    assert "40.00" in body   # spent: 30 + 15.50 - 5.50 refund
    assert "60.00" in body   # remaining
    assert 'aria-label="40.0% used"' in body


def test_budget_carries_forward_until_changed(app, post, category):
    food = category("Food")
    post("/budgets", {"month": "2026-08", f"budget_{food}": "200"})
    post("/budgets", {"month": "2026-11", f"budget_{food}": "250"})
    with app.app_context():
        assert db.budgets_for_month("2026-07") == {}
        assert db.budgets_for_month("2026-10") == {food: (20000, "2026-08")}
        assert db.budgets_for_month("2027-01") == {food: (25000, "2026-11")}


def test_clearing_a_budget_removes_only_that_month(app, post, client, category):
    food = category("Food")
    post("/budgets", {"month": "2026-08", f"budget_{food}": "200"})
    post("/budgets", {"month": "2026-09", f"budget_{food}": "300"})
    post("/budgets", {"month": "2026-09", f"budget_{food}": ""})
    with app.app_context():
        assert db.budgets_for_month("2026-09") == {food: (20000, "2026-08")}
    assert "carried from 2026-08" in client.get("/budgets?month=2026-09").get_data(as_text=True)


def test_overspent_budget_is_flagged(post, client, category, add_tx):
    fun = category("Fun")
    post("/budgets", {"month": "2026-10", f"budget_{fun}": "10"})
    add_tx(date="2026-10-04", amount="25", category_id=fun)
    body = client.get("/budgets?month=2026-10").get_data(as_text=True)
    assert "-15.00" in body
    assert 'class="over"' in body
    assert 'aria-label="100% used"' in body


def test_invalid_budget_values_are_rejected_and_nothing_saved(app, post, category):
    food = category("Food")
    rent = category("Rent")
    r = post("/budgets", {"month": "2026-10", f"budget_{food}": "lots",
                          f"budget_{rent}": "-5"})
    assert r.status_code == 400
    body = r.get_data(as_text=True)
    assert "Food: not a valid amount" in body and "a budget cannot be negative" in body
    assert 'value="lots"' in body
    with app.app_context():
        assert db.budgets_for_month("2026-10") == {}
    assert post("/budgets", {"month": "2026-1"}).status_code == 400


def test_budget_page_month_navigation(client):
    body = client.get("/budgets?month=2026-01").get_data(as_text=True)
    assert "January 2026" in body
    assert "month=2025-12" in body and "month=2026-02" in body
