import sqlite3

from budgetbook import create_app, db


def make_pair(post, app, add_tx, txs):
    for name in ("Current", "Savings"):
        post("/accounts", {"name": name, "kind": "current", "opening": "0"})
    with app.app_context():
        acc = {a["name"]: a["id"] for a in db.list_accounts()}
    add_tx(payee="To savings", amount="200.00", account_id=acc["Current"])
    add_tx(payee="From current", amount="200.00", kind="income",
           account_id=acc["Savings"])
    add_tx(payee="Cafe", amount="4.00", account_id=acc["Current"])
    by = {t["payee"]: t["id"] for t in txs()}
    return by, acc


def link(post, a, b):
    return post("/transactions/bulk", {"ids": [str(a), str(b)], "action": "transfer"},
                follow_redirects=True).get_data(as_text=True)


def test_transfer_left_out_of_totals_and_report(post, app, client, add_tx, txs):
    by, _ = make_pair(post, app, add_tx, txs)
    with app.app_context():
        assert db.month_totals("2026-10") == (20000, 20400)
    body = link(post, by["To savings"], by["From current"])
    assert "Marked as a transfer" in body
    with app.app_context():
        assert db.month_totals("2026-10") == (0, 400)
        assert [r["category"] for r in db.category_net("2026-10")] == [None]
        assert db.category_net("2026-10")[0]["net_cents"] == -400
        assert sum(r["net_cents"] for r in db.year_category_months(2026)) == -400
        assert sum(r["net_cents"] for r in
                   db.category_net_between("2026-01-01", "2027-01-01")) == -400
    html = client.get("/?month=2026-10").get_data(as_text=True)
    assert html.count("(transfer)") == 2
    # Balances still count the money moving.
    with app.app_context():
        bal = {a["name"]: a["balance_cents"] for a in db.list_accounts()}
    assert bal == {"Current": -20400, "Savings": 20000}


def test_rejects_bad_pairs(post, app, add_tx, txs):
    by, _ = make_pair(post, app, add_tx, txs)
    assert "exactly two" in post("/transactions/bulk",
                                 {"ids": [str(by["Cafe"])], "action": "transfer"},
                                 follow_redirects=True).get_data(as_text=True)
    assert "one amount out" in link(post, by["To savings"], by["Cafe"])
    add_tx(payee="Same", amount="200.00", kind="income",
           account_id=next(t["account_id"] for t in txs() if t["payee"] == "To savings"))
    same = next(t["id"] for t in txs() if t["payee"] == "Same")
    assert "same account" in link(post, by["To savings"], same)
    assert all(t["transfer_id"] is None for t in txs())
    link(post, by["To savings"], by["From current"])
    assert "already part" in link(post, by["To savings"], same)


def test_unlink_restores_totals(post, app, add_tx, txs):
    by, _ = make_pair(post, app, add_tx, txs)
    link(post, by["To savings"], by["From current"])
    assert post(f"/transactions/{by['From current']}/unlink").status_code == 302
    assert all(t["transfer_id"] is None for t in txs())
    with app.app_context():
        assert db.month_totals("2026-10") == (20000, 20400)
    assert post(f"/transactions/{by['Cafe']}/unlink").status_code == 404


def test_deleting_one_half_frees_the_other(post, app, add_tx, txs):
    by, _ = make_pair(post, app, add_tx, txs)
    link(post, by["To savings"], by["From current"])
    post(f"/transactions/{by['To savings']}/delete")
    left = next(t for t in txs() if t["payee"] == "From current")
    assert left["transfer_id"] is None


def test_changing_an_amount_breaks_the_transfer(post, app, add_tx, txs):
    by, _ = make_pair(post, app, add_tx, txs)
    link(post, by["To savings"], by["From current"])
    tx = next(t for t in txs() if t["payee"] == "To savings")
    post(f"/transactions/{tx['id']}/edit",
         {"date": tx["date"], "kind": "expense", "amount": "150.00",
          "payee": "To savings", "account_id": tx["account_id"]})
    assert all(t["transfer_id"] is None for t in txs())


def test_unlink_needs_csrf(client):
    assert client.post("/transactions/1/unlink").status_code == 400


def test_migrates_version_5_database(tmp_path):
    path = str(tmp_path / "old.db")
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE categories (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE);
        CREATE TABLE accounts (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE,
            kind TEXT NOT NULL DEFAULT 'current', opening_cents INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE transactions (
            id INTEGER PRIMARY KEY, date TEXT NOT NULL, amount_cents INTEGER NOT NULL,
            payee TEXT NOT NULL,
            category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL);
        INSERT INTO transactions (date, amount_cents, payee) VALUES ('2026-01-02', -500, 'A');
        INSERT INTO transactions (date, amount_cents, payee) VALUES ('2026-01-02', 500, 'B');
        PRAGMA user_version = 5;
    """)
    conn.commit()
    conn.close()
    app = create_app({"TESTING": True, "SECRET_KEY": "t", "DATABASE": path})
    with app.app_context():
        rows = db.list_transactions()
        assert len(rows) == 2 and all(r["transfer_id"] is None for r in rows)
        db.link_transfer(rows[0]["id"], rows[1]["id"])
        assert db.month_totals("2026-01") == (0, 0)
    conn = sqlite3.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    conn.close()
