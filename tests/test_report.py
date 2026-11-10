import re

from budgetbook import db


def test_month_totals_and_category_net(app, add_tx, category):
    food = category("Food")
    add_tx(date="2026-10-01", kind="income", amount="1000", payee="Job")
    add_tx(date="2026-10-02", amount="40", category_id=food)
    add_tx(date="2026-10-03", amount="10", category_id=food)
    add_tx(date="2026-10-04", amount="5")
    add_tx(date="2026-09-30", amount="999")
    with app.app_context():
        assert db.month_totals("2026-10") == (100000, 5500)
        rows = {r["category"]: (r["net_cents"], r["count"]) for r in db.category_net("2026-10")}
        assert rows == {"Food": (-5000, 2), None: (100000 - 500, 2)}


def test_report_page_renders_totals_and_svg_bars(client, add_tx, category, post):
    food = category("Food")
    fun = category("Fun")
    post("/budgets", {"month": "2026-10", f"budget_{food}": "30"})
    add_tx(date="2026-10-01", kind="income", amount="200", payee="Job")
    add_tx(date="2026-10-02", amount="40", category_id=food)
    add_tx(date="2026-10-03", amount="10", category_id=fun)
    body = client.get("/report?month=2026-10").get_data(as_text=True)
    assert "October 2026" in body
    assert "200.00" in body and "50.00" in body and "+150.00" in body
    # the largest category gets a full-width bar, others scale against it
    assert '<rect width="100.0" height="12" class="expense"/>' in body
    assert '<rect width="25.0" height="12" class="expense"/>' in body
    # food is over its 30.00 budget
    assert re.search(r'class="num neg">\s*30\.00', body)
    assert "<script" not in body


def test_report_trend_covers_six_months(client, add_tx):
    add_tx(date="2026-05-10", amount="10")
    add_tx(date="2026-10-10", amount="20")
    body = client.get("/report?month=2026-10").get_data(as_text=True)
    months = re.findall(r'href="/report\?month=(\d{4}-\d{2})">\1<', body)
    assert months == ["2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]
    assert '<rect width="50.0" height="12" class="expense"/>' in body


def test_report_empty_month_and_bad_month_param(client):
    body = client.get("/report?month=2020-01").get_data(as_text=True)
    assert "No spending this month." in body and "No income this month." in body
    assert '<rect width="0" height="12"' in body
    assert client.get("/report?month=<x>").status_code == 200


def test_report_escapes_category_names(client, add_tx, category):
    cid = category("<i>Evil</i>")
    add_tx(date="2026-10-02", category_id=cid)
    body = client.get("/report?month=2026-10").get_data(as_text=True)
    assert "<i>Evil</i>" not in body and "&lt;i&gt;Evil" in body
