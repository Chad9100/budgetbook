from budgetbook import db


def test_add_rename_and_list_categories(post, client, category):
    cid = category("Food")
    assert "Food" in client.get("/categories").get_data(as_text=True)
    assert post(f"/categories/{cid}/rename", {"name": "Groceries"}).status_code == 302
    body = client.get("/categories").get_data(as_text=True)
    assert "Groceries" in body and 'value="Food"' not in body


def test_duplicate_and_blank_names_are_rejected(post, category):
    category("Food")
    r = post("/categories", {"name": "food"})
    assert r.status_code == 400
    assert "already exists" in r.get_data(as_text=True)
    assert post("/categories", {"name": "   "}).status_code == 400
    assert post("/categories", {"name": "x" * 61}).status_code == 400


def test_rename_conflict_and_unknown(post, category):
    category("Food")
    rent = category("Rent")
    assert post(f"/categories/{rent}/rename", {"name": "FOOD"}).status_code == 400
    assert post("/categories/999/rename", {"name": "X"}).status_code == 404


def test_delete_category_uncategorises_and_removes_rules_and_budgets(
        app, post, category, add_tx, txs):
    fun = category("Fun")
    add_tx(payee="Cinema", category_id=fun)
    post("/rules", {"pattern": "cinema", "category_id": str(fun)})
    post("/budgets", {"month": "2026-10", f"budget_{fun}": "50"})
    assert post(f"/categories/{fun}/delete").status_code == 302
    assert txs()[0]["category_id"] is None
    with app.app_context():
        assert db.list_rules() == []
        assert db.budgets_for_month("2026-10") == {}
    assert post(f"/categories/{fun}/delete").status_code == 404


def test_category_usage_counts(app, post, category, add_tx):
    food = category("Food")
    add_tx(category_id=food)
    add_tx(category_id=food)
    post("/rules", {"pattern": "shop", "category_id": str(food)})
    with app.app_context():
        assert db.category_usage()[food] == {"transactions": 2, "rules": 1}
