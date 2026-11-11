import re


def cells(body, name):
    """The text of every <td> in the table row whose header is ``name``."""
    row = re.search(r"<tr[^>]*><th>%s</th>(.*?)</tr>" % re.escape(name), body, re.S).group(1)
    return [re.sub(r"<[^>]+>|\s+", "", c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]


def test_year_report_month_by_month_with_totals(client, add_tx, category):
    food = category("Food")
    fun = category("Fun")
    add_tx(date="2026-01-10", amount="40", category_id=food)
    add_tx(date="2026-01-20", amount="10", category_id=food)
    add_tx(date="2026-03-05", amount="25.50", category_id=food)
    add_tx(date="2026-12-31", amount="7", category_id=fun)
    add_tx(date="2025-12-31", amount="999", category_id=fun)
    add_tx(date="2027-01-01", amount="999", category_id=fun)
    body = client.get("/report/year?year=2026").get_data(as_text=True)
    assert "Year report &middot; 2026" in body
    c = cells(body, "Food")
    assert c[0] == "50.00" and c[1] == "&ndash;" and c[2] == "25.50" and c[-1] == "75.50"
    f = cells(body, "Fun")
    assert f[11] == "7.00" and f[-1] == "7.00"
    total = cells(body, "Total")
    assert total[0] == "50.00" and total[11] == "7.00" and total[-1] == "82.50"
    assert body.index(">Food<") < body.index(">Fun<")


def test_year_report_refund_and_income(client, add_tx, category):
    food = category("Food")
    add_tx(date="2026-02-01", amount="30", category_id=food)
    add_tx(date="2026-02-02", kind="income", amount="10", category_id=food)
    add_tx(date="2026-02-03", kind="income", amount="500", payee="Job")
    body = client.get("/report/year?year=2026").get_data(as_text=True)
    assert cells(body, "Food")[1] == "20.00"
    income_part = body.split("Income by category")[1]
    assert cells(income_part, "Uncategorised")[-1] == "500.00"


def test_year_report_empty_and_bad_year(client):
    body = client.get("/report/year?year=2026").get_data(as_text=True)
    assert "No spending in 2026." in body and "No income in 2026." in body
    assert client.get("/report/year?year=abc").status_code == 200
    assert client.get("/report/year?year=99999999").status_code == 200
    assert "2025" in client.get("/report/year?year=2026").get_data(as_text=True)


def test_year_report_escapes_and_is_linked_from_monthly_report(client, add_tx, category):
    cid = category("<b>x</b>")
    add_tx(date="2026-04-01", category_id=cid)
    body = client.get("/report/year?year=2026").get_data(as_text=True)
    assert "<b>x</b>" not in body and "&lt;b&gt;x" in body
    monthly = client.get("/report?month=2026-10").get_data(as_text=True)
    assert 'href="/report/year?year=2026"' in monthly
