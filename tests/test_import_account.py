import re

from budgetbook import db
from test_accounts import make_account
from test_import_views import BANK_CSV, MAPPING, import_id, upload


def test_import_into_chosen_account(post, app, txs):
    aid = make_account(post, app, name="Current", opening="100.00")
    iid = import_id(upload(post, BANK_CSV))
    r = post(f"/import/{iid}", dict(MAPPING, account_id=str(aid)))
    assert r.status_code == 200
    assert [t["account_id"] for t in txs()] == [aid, aid, aid]


def test_import_without_account_leaves_none(post, app, txs):
    make_account(post, app)
    post(f"/import/{import_id(upload(post, BANK_CSV))}", MAPPING)
    assert [t["account_id"] for t in txs()] == [None, None, None]


def test_import_rejects_unknown_account(post, txs):
    iid = import_id(upload(post, BANK_CSV))
    r = post(f"/import/{iid}", dict(MAPPING, account_id="99"))
    assert r.status_code == 400
    assert "Choose an existing account." in r.get_data(as_text=True)
    assert txs() == []
    r = post(f"/import/{iid}", dict(MAPPING, account_id="abc"))
    assert r.status_code == 400


def test_map_page_offers_accounts_only_when_they_exist(post, app, client):
    iid = import_id(upload(post, BANK_CSV))
    assert "Account for these transactions" not in client.get(f"/import/{iid}").get_data(as_text=True)
    aid = make_account(post, app, name="Savings", kind="savings")
    body = client.get(f"/import/{iid}").get_data(as_text=True)
    assert f'<option value="{aid}" >Savings' in body


def test_preview_keeps_chosen_account_selected(post, app):
    aid = make_account(post, app)
    iid = import_id(upload(post, BANK_CSV))
    r = post(f"/import/{iid}", dict(MAPPING, account_id=str(aid), action="preview"))
    assert f'<option value="{aid}" selected>Current' in r.get_data(as_text=True)


def test_running_balance_in_account_view(post, app, client, add_tx):
    aid = make_account(post, app, opening="100.00")
    add_tx(date="2026-10-01", amount="30.00", account_id=aid)
    add_tx(date="2026-10-03", amount="50.00", kind="income", account_id=aid)
    add_tx(date="2026-10-02", amount="20.00", account_id=aid)
    add_tx(date="2026-10-02", amount="999.00")  # other account: ignored
    with app.app_context():
        assert list(db.running_balances(aid).values()) == [7000, 5000, 10000]
        assert db.running_balances(999) == {}
    body = client.get(f"/?account={aid}").get_data(as_text=True)
    assert "<th class=\"num\">Balance</th>" in body
    cells = re.findall(r'<td class="num">([^<]*)</td>', body)
    # newest first: 100-30-20+50 = 100.00, then 50.00, then 70.00
    assert cells == ["100.00", "50.00", "70.00"]
    assert "Balance</th>" not in client.get("/?clear=1").get_data(as_text=True)
    assert "Balance</th>" not in client.get("/?account=none").get_data(as_text=True)
