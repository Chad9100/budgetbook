from budgetbook.rules import pick_category


def test_pick_category_is_case_insensitive_substring():
    rules = [("tesco", 1), ("shell", 2)]
    assert pick_category("TESCO STORES 1234", rules) == 1
    assert pick_category("Shell Garage", rules) == 2
    assert pick_category("Amazon", rules) is None


def test_longest_pattern_wins_and_ties_go_to_first():
    rules = [("amazon", 1), ("amazon prime", 2), ("prime", 3), ("amazon", 4)]
    assert pick_category("AMAZON PRIME VIDEO", rules) == 2
    assert pick_category("amazon.co.uk", rules) == 1


def test_whitespace_is_normalised_and_blank_patterns_ignored():
    rules = [("  ", 9), ("corner  shop", 5)]
    assert pick_category("The Corner   Shop", rules) == 5
    assert pick_category("anything", [("", 9)]) is None


def test_rules_view_add_apply_and_delete(post, client, category, add_tx, txs):
    groceries = category("Groceries")
    add_tx(payee="TESCO 123")
    add_tx(payee="Cinema")
    assert txs()[0]["category_id"] is None

    r = post("/rules", {"pattern": "tesco", "category_id": str(groceries)})
    assert r.status_code == 302
    assert "tesco" in client.get("/rules").get_data(as_text=True)

    r = post("/rules/apply", follow_redirects=True)
    assert "Categorised 1 transaction." in r.get_data(as_text=True)
    assert [t["category_id"] for t in txs()] == [groceries, None]

    # new transactions without a category are categorised on save
    add_tx(payee="tesco express")
    assert txs()[-1]["category_id"] == groceries

    from budgetbook import db
    with client.application.app_context():
        rule_id = db.list_rules()[0]["id"]
    assert post(f"/rules/{rule_id}/delete").status_code == 302
    assert post(f"/rules/{rule_id}/delete").status_code == 404


def test_rules_view_validation(post, category):
    category("Fun")
    r = post("/rules", {"pattern": "", "category_id": "999"})
    assert r.status_code == 400
    body = r.get_data(as_text=True)
    assert "Pattern is required." in body and "Unknown category." in body
