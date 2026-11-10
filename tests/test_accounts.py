import sqlite3

from budgetbook import create_app, db


def make_account(post, app, name="Current", opening="100.00", kind="current"):
    r = post("/accounts", {"name": name, "kind": kind, "opening": opening})
    assert r.status_code == 302
    with app.app_context():
        return next(a["id"] for a in db.list_accounts() if a["name"] == name)


def test_add_account_and_balance(post, app, client, add_tx):
    aid = make_account(post, app, opening="100.00")
    add_tx(amount="30.00", account_id=aid)
    add_tx(amount="5.00", kind="income", account_id=aid)
    add_tx(amount="99.00")  # no account: not in the balance
    with app.app_context():
        acc = db.list_accounts()[0]
        assert acc["balance_cents"] == 7500 and acc["tx_count"] == 2
    body = client.get("/accounts").get_data(as_text=True)
    assert "Current" in body and "75.00" in body


def test_account_validation(post, app):
    make_account(post, app)
    assert post("/accounts", {"name": "current"}).status_code == 400
    assert post("/accounts", {"name": ""}).status_code == 400
    assert post("/accounts", {"name": "X", "kind": "bogus"}).status_code == 400
    assert post("/accounts", {"name": "Y", "opening": "abc"}).status_code == 400


def test_unknown_account_rejected_on_transaction(add_tx, txs):
    assert add_tx(account_id=99).status_code == 400
    assert txs() == []


def test_filter_by_account_and_edit(post, app, client, add_tx, txs):
    aid = make_account(post, app, name="Savings", kind="savings")
    add_tx(payee="InAcc", account_id=aid)
    add_tx(payee="NoAcc")
    body = client.get(f"/?account={aid}").get_data(as_text=True)
    assert "InAcc" in body and "NoAcc" not in body
    body = client.get("/?account=none").get_data(as_text=True)
    assert "NoAcc" in body and "InAcc" not in body
    tid = next(t["id"] for t in txs() if t["payee"] == "NoAcc")
    post(f"/transactions/{tid}/edit", {"date": "2026-10-05", "kind": "expense",
                                       "amount": "1.00", "payee": "NoAcc",
                                       "account_id": aid})
    assert next(t for t in txs() if t["id"] == tid)["account_id"] == aid


def test_delete_account_keeps_transactions(post, app, add_tx, txs):
    aid = make_account(post, app)
    add_tx(account_id=aid)
    assert post(f"/accounts/{aid}/delete").status_code == 302
    assert len(txs()) == 1 and txs()[0]["account_id"] is None
    assert post("/accounts/999/delete").status_code == 404


def test_account_post_needs_csrf(client):
    assert client.post("/accounts", data={"name": "X"}).status_code == 400


def test_migrates_version_4_database(tmp_path):
    path = str(tmp_path / "old.db")
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE categories (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE);
        CREATE TABLE transactions (
            id INTEGER PRIMARY KEY, date TEXT NOT NULL, amount_cents INTEGER NOT NULL,
            payee TEXT NOT NULL,
            category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now')));
        INSERT INTO categories (name) VALUES ('Food');
        INSERT INTO transactions (date, amount_cents, payee, category_id)
            VALUES ('2026-01-02', -1250, 'Cafe', 1);
        PRAGMA user_version = 4;
    """)
    conn.commit()
    conn.close()
    app = create_app({"TESTING": True, "SECRET_KEY": "t", "DATABASE": path})
    with app.app_context():
        rows = db.list_transactions()
        assert len(rows) == 1 and rows[0]["payee"] == "Cafe"
        assert rows[0]["amount_cents"] == -1250 and rows[0]["account_id"] is None
        assert db.add_account("Main") > 0
    conn = sqlite3.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    conn.close()
