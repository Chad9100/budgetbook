import re


def cells(body, name):
    row = re.search(r"<tr[^>]*><th>%s</th>(.*?)</tr>" % re.escape(name), body, re.S).group(1)
    return [re.sub(r"<[^>]+>|\s+", "", c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]


def test_averages_over_three_six_twelve_months(client, add_tx, category):
    food = category("Food")
    add_tx(date="2026-09-10", amount="90", category_id=food)    # in all windows
    add_tx(date="2026-06-10", amount="180", category_id=food)   # 4 months back: 6 and 12 only
    add_tx(date="2025-12-10", amount="360", category_id=food)   # 10 months back: 12 only
    add_tx(date="2025-09-30", amount="999", category_id=food)   # 13 months back: none
    add_tx(date="2026-10-01", amount="999", category_id=food)   # chosen month itself: excluded
    body = client.get("/report/averages?month=2026-10").get_data(as_text=True)
    assert "Last 3 months" in body and "Last 12 months" in body
    # 90/3, (90+180)/6, (90+180+360)/12
    assert cells(body, "Food") == ["30.00", "45.00", "52.50"]
    assert cells(body, "Total") == ["30.00", "45.00", "52.50"]


def test_averages_net_refunds_income_and_ordering(client, add_tx, category):
    food = category("Food")
    fun = category("Fun")
    pay = category("Pay")
    add_tx(date="2026-08-01", amount="60", category_id=food)
    add_tx(date="2026-08-02", kind="income", amount="30", category_id=food)
    add_tx(date="2026-08-03", amount="300", category_id=fun)
    add_tx(date="2026-08-04", kind="income", amount="900", category_id=pay)
    add_tx(date="2026-08-05", amount="1", payee="x")
    body = client.get("/report/averages?month=2026-10").get_data(as_text=True)
    assert cells(body, "Food")[0] == "10.00"
    assert "Pay" not in body.split("<table")[1]
    assert body.index(">Fun<") < body.index(">Food<")
    assert cells(body, "Uncategorised")[0] == "0.33"


def test_averages_empty_default_month_and_link(client, add_tx):
    body = client.get("/report/averages").get_data(as_text=True)
    assert "No spending in the 12 months before" in body
    assert client.get("/report/averages?month=bogus").status_code == 200
    year = client.get("/report/year?year=2026").get_data(as_text=True)
    assert 'href="/report/averages"' in year


def test_averages_escapes_names(client, add_tx, category):
    cid = category("<i>x</i>")
    add_tx(date="2026-09-01", category_id=cid)
    body = client.get("/report/averages?month=2026-10").get_data(as_text=True)
    assert "<i>x</i>" not in body and "&lt;i&gt;x" in body
