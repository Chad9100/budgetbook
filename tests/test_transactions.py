def test_empty_list_page(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "No transactions here yet" in r.get_data(as_text=True)


def test_add_expense_and_income_stored_as_signed_cents(add_tx, txs, client):
    assert add_tx(amount="12.34", payee="Bakery").status_code == 302
    add_tx(kind="income", amount="2,500", payee="Employer", date="2026-10-25")
    stored = txs()
    assert [(t["payee"], t["amount_cents"]) for t in stored] == [
        ("Bakery", -1234), ("Employer", 250000)]
    body = client.get("/?month=2026-10").get_data(as_text=True)
    assert "-12.34" in body and "+2,500.00" in body
    assert "in <span class=\"pos\">2,500.00</span>" in body


def test_add_redirects_to_month_of_transaction(add_tx):
    r = add_tx(date="2026-03-15")
    assert r.headers["Location"].endswith("/?month=2026-03")


def test_add_validation_errors_keep_input(add_tx, txs):
    r = add_tx(date="2026-02-30", amount="abc", payee="  ", note="keep me")
    assert r.status_code == 400
    body = r.get_data(as_text=True)
    assert "Date must be a valid date" in body
    assert "Amount: not a valid amount" in body
    assert "Payee is required." in body
    assert "keep me" in body
    assert txs() == []


def test_amount_must_be_positive_and_category_must_exist(add_tx, txs):
    body = add_tx(amount="-5").get_data(as_text=True)
    assert "greater than zero" in body
    assert add_tx(category_id="42").status_code == 400
    assert add_tx(kind="transfer").status_code == 400
    assert txs() == []


def test_edit_transaction(add_tx, post, client, txs, category):
    fun = category("Fun")
    add_tx(amount="5", payee="Cinema")
    tx_id = txs()[0]["id"]
    form = client.get(f"/transactions/{tx_id}/edit").get_data(as_text=True)
    assert 'value="5.00"' in form and 'value="Cinema"' in form
    r = post(f"/transactions/{tx_id}/edit", {
        "date": "2026-10-06", "kind": "expense", "amount": "7.50",
        "payee": "Cinema City", "category_id": str(fun), "note": "with Sam"})
    assert r.status_code == 302
    t = txs()[0]
    assert (t["date"], t["amount_cents"], t["payee"], t["category_id"], t["note"]) == (
        "2026-10-06", -750, "Cinema City", fun, "with Sam")


def test_edit_and_delete_unknown_transaction_404(client, post):
    assert client.get("/transactions/99/edit").status_code == 404
    assert post("/transactions/99/delete").status_code == 404


def test_delete_transaction(add_tx, post, txs):
    add_tx()
    tx_id = txs()[0]["id"]
    r = post(f"/transactions/{tx_id}/delete", follow_redirects=True)
    assert "Transaction deleted." in r.get_data(as_text=True)
    assert txs() == []


def test_filters_by_month_search_and_category(add_tx, client, category):
    food = category("Food")
    add_tx(date="2026-09-30", payee="September shop")
    add_tx(date="2026-10-01", payee="October cafe", category_id=food)
    add_tx(date="2026-10-31", payee="Halloween 100%_off", note="costume")
    body = client.get("/?month=2026-10").get_data(as_text=True)
    assert "October cafe" in body and "Halloween" in body and "September shop" not in body
    body = client.get("/?q=COSTUME").get_data(as_text=True)
    assert "Halloween" in body and "October cafe" not in body
    # LIKE wildcards in the search are literal
    body = client.get("/?q=0%25_").get_data(as_text=True)
    assert "Halloween" in body and "September shop" not in body
    body = client.get(f"/?category={food}").get_data(as_text=True)
    assert "October cafe" in body and "Halloween" not in body
    body = client.get("/?category=none").get_data(as_text=True)
    assert "October cafe" not in body and "Halloween" in body
    # junk filters are ignored rather than crashing
    assert client.get("/?month=garbage&category=x").status_code == 200


def test_output_is_escaped(add_tx, client):
    add_tx(payee="<script>alert(1)</script>", note="<b>bold</b>")
    body = client.get("/").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body and "&lt;b&gt;bold" in body


def test_export_csv(add_tx, client, category):
    cat = category("Misc")
    add_tx(date="2026-10-02", amount="3.10", payee="=HYPERLINK(1)", category_id=cat)
    add_tx(date="2026-10-01", kind="income", amount="50", payee="Gift")
    add_tx(date="2026-11-01", payee="Other month")
    r = client.get("/export.csv?month=2026-10")
    assert r.mimetype == "text/csv"
    assert "budgetbook-2026-10.csv" in r.headers["Content-Disposition"]
    assert r.get_data(as_text=True).splitlines() == [
        "date,amount,payee,category,note",
        "2026-10-01,50.00,Gift,,",
        "2026-10-02,-3.10,'=HYPERLINK(1),Misc,",
    ]
