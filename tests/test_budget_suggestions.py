from budgetbook import db


def _budgets(app, month):
    with app.app_context():
        return db.budgets_for_month(month)


def test_apply_window_average_as_budgets(app, post, client, category, add_tx):
    food = category("Food")
    fun = category("Fun")
    category("Unused")
    add_tx(date="2026-09-10", amount="90", category_id=food)
    add_tx(date="2026-06-10", amount="180", category_id=food)
    add_tx(date="2026-09-11", amount="30", category_id=fun)
    add_tx(date="2026-09-12", amount="500")  # uncategorised: no budget
    r = post("/report/averages/suggest", {"month": "2026-10", "window": "6"})
    assert r.status_code == 302
    assert _budgets(app, "2026-10") == {food: (4500, "2026-10"), fun: (500, "2026-10")}
    body = client.get("/budgets?month=2026-10").get_data(as_text=True)
    assert "Set 2 budgets for 2026-10 from the 6-month average." in body


def test_existing_budget_for_that_month_is_kept(app, post, category, add_tx):
    food = category("Food")
    fun = category("Fun")
    add_tx(date="2026-09-10", amount="90", category_id=food)
    add_tx(date="2026-09-11", amount="30", category_id=fun)
    post("/budgets", {"month": "2026-10", f"budget_{food}": "77"})
    post("/budgets", {"month": "2026-08", f"budget_{fun}": "5"})  # carried, not set in Oct
    post("/report/averages/suggest", {"month": "2026-10", "window": "3"})
    assert _budgets(app, "2026-10") == {food: (7700, "2026-10"), fun: (1000, "2026-10")}


def test_invalid_input_and_csrf(client, post):
    assert post("/report/averages/suggest", {"month": "bad", "window": "3"}).status_code == 400
    assert post("/report/averages/suggest", {"month": "2026-10", "window": "4"}).status_code == 400
    assert post("/report/averages/suggest", {"month": "2026-10", "window": "x"}).status_code == 400
    assert client.post("/report/averages/suggest",
                       data={"month": "2026-10", "window": "3"}).status_code == 400


def test_averages_page_has_suggest_buttons(client, add_tx):
    add_tx(date="2026-09-10", amount="9")
    body = client.get("/report/averages?month=2026-10").get_data(as_text=True)
    assert "Use 3-month averages" in body and "Use 12-month averages" in body
