"""SQLite storage. Every amount is stored as integer cents (negative = money out)."""
import json
import os
import sqlite3
from collections import Counter

from flask import current_app, g

from .money import month_range

# 2: import_profiles (added with CREATE TABLE IF NOT EXISTS, so opening a
#    version-1 database upgrades it in place without touching existing data)
# 3: rules.match_type (added with ALTER TABLE when missing; existing rules
#    keep working as "contains")
# 4: rules.min_cents / rules.max_cents (nullable ALTERs; NULL = no limit)
# 5: accounts table and transactions.account_id (nullable ALTER; existing
#    transactions stay on "no account")
SCHEMA_VERSION = 5

SCHEMA = """
CREATE TABLE IF NOT EXISTS categories (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE
);
CREATE TABLE IF NOT EXISTS accounts (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE COLLATE NOCASE,
    kind          TEXT NOT NULL DEFAULT 'current',
    opening_cents INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS transactions (
    id           INTEGER PRIMARY KEY,
    date         TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    payee        TEXT NOT NULL,
    category_id  INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    note         TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    account_id   INTEGER REFERENCES accounts(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS ix_transactions_date ON transactions(date);
CREATE TABLE IF NOT EXISTS rules (
    id          INTEGER PRIMARY KEY,
    pattern     TEXT NOT NULL,
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    match_type  TEXT NOT NULL DEFAULT 'contains',
    min_cents   INTEGER,
    max_cents   INTEGER
);
CREATE TABLE IF NOT EXISTS budgets (
    category_id  INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    month        TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    PRIMARY KEY (category_id, month)
);
CREATE TABLE IF NOT EXISTS pending_imports (
    id         INTEGER PRIMARY KEY,
    filename   TEXT NOT NULL,
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS import_profiles (
    id         INTEGER PRIMARY KEY,
    header_key TEXT NOT NULL UNIQUE,
    name       TEXT NOT NULL,
    mapping    TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

DEFAULT_CATEGORIES = ["Groceries", "Rent", "Utilities", "Transport",
                      "Eating out", "Entertainment", "Health", "Shopping",
                      "Salary", "Other income"]


def connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def ensure_schema(conn):
    conn.executescript(SCHEMA)
    rule_cols = {r[1] for r in conn.execute("PRAGMA table_info(rules)")}
    if "match_type" not in rule_cols:
        conn.execute("ALTER TABLE rules ADD COLUMN"
                     " match_type TEXT NOT NULL DEFAULT 'contains'")
    for col in ("min_cents", "max_cents"):
        if col not in rule_cols:
            conn.execute(f"ALTER TABLE rules ADD COLUMN {col} INTEGER")
    tx_cols = {r[1] for r in conn.execute("PRAGMA table_info(transactions)")}
    if "account_id" not in tx_cols:
        conn.execute("ALTER TABLE transactions ADD COLUMN"
                     " account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_transactions_account"
                 " ON transactions(account_id)")
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()


def backup_file(src, dest):
    """Write a consistent copy of the database at ``src`` to ``dest`` using
    SQLite's online backup API, so it is safe while the app is running.
    Returns the number of transactions in the copy."""
    if not os.path.isfile(src):
        raise FileNotFoundError(f"no database at {src}")
    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    source = sqlite3.connect(src)
    target = sqlite3.connect(dest)
    try:
        source.backup(target)
        return target.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    finally:
        target.close()
        source.close()


def init_file(path, seed=False):
    """Create the database file (and its folder) if needed. Returns True when
    default categories were added."""
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    conn = connect(path)
    try:
        ensure_schema(conn)
        added = False
        if seed and conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0] == 0:
            conn.executemany("INSERT INTO categories (name) VALUES (?)",
                             [(n,) for n in DEFAULT_CATEGORIES])
            conn.commit()
            added = True
        return added
    finally:
        conn.close()


def get_db():
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def close_db(exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


# ---------------------------------------------------------------- categories

def list_categories():
    return get_db().execute(
        "SELECT id, name FROM categories ORDER BY name COLLATE NOCASE").fetchall()


def get_category(cat_id):
    return get_db().execute("SELECT id, name FROM categories WHERE id = ?",
                            (cat_id,)).fetchone()


def add_category(name):
    conn = get_db()
    try:
        cur = conn.execute("INSERT INTO categories (name) VALUES (?)", (name,))
    except sqlite3.IntegrityError:
        raise ValueError(f"category {name!r} already exists") from None
    conn.commit()
    return cur.lastrowid


def rename_category(cat_id, name):
    conn = get_db()
    try:
        cur = conn.execute("UPDATE categories SET name = ? WHERE id = ?",
                           (name, cat_id))
    except sqlite3.IntegrityError:
        raise ValueError(f"category {name!r} already exists") from None
    conn.commit()
    return cur.rowcount > 0


def delete_category(cat_id):
    """Delete a category; its transactions become uncategorised and its
    rules and budgets are removed."""
    conn = get_db()
    cur = conn.execute("DELETE FROM categories WHERE id = ?", (cat_id,))
    conn.commit()
    return cur.rowcount > 0


# ------------------------------------------------------------------ accounts

ACCOUNT_KINDS = {"current": "Current", "savings": "Savings",
                 "credit": "Credit card", "cash": "Cash"}


def list_accounts():
    """Accounts with ``balance_cents`` (opening balance plus all their
    transactions) and ``tx_count``."""
    return get_db().execute(
        "SELECT a.id, a.name, a.kind, a.opening_cents,"
        " a.opening_cents + COALESCE(SUM(t.amount_cents), 0) AS balance_cents,"
        " COUNT(t.id) AS tx_count"
        " FROM accounts a LEFT JOIN transactions t ON t.account_id = a.id"
        " GROUP BY a.id ORDER BY a.name COLLATE NOCASE").fetchall()


def get_account(account_id):
    return get_db().execute(
        "SELECT id, name, kind, opening_cents FROM accounts WHERE id = ?",
        (account_id,)).fetchone()


def add_account(name, kind="current", opening_cents=0):
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO accounts (name, kind, opening_cents) VALUES (?, ?, ?)",
            (name, kind, opening_cents))
    except sqlite3.IntegrityError:
        raise ValueError(f"account {name!r} already exists") from None
    conn.commit()
    return cur.lastrowid


def delete_account(account_id):
    """Delete an account; its transactions are kept with no account."""
    conn = get_db()
    cur = conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
    conn.commit()
    return cur.rowcount > 0


# -------------------------------------------------------------- transactions

_TX_SELECT = """
SELECT t.id, t.date, t.amount_cents, t.payee, t.category_id, t.note,
       c.name AS category, t.account_id, a.name AS account
FROM transactions t LEFT JOIN categories c ON c.id = t.category_id
LEFT JOIN accounts a ON a.id = t.account_id
"""


def list_transactions(month=None, q="", category="", account=""):
    """``category`` is "" (all), "none" (uncategorised) or a category id;
    ``account`` is "" (all), "none" (no account) or an account id."""
    where, args = [], []
    if month:
        start, end = month_range(month)
        where.append("t.date >= ? AND t.date < ?")
        args += [start, end]
    if q:
        where.append("(t.payee LIKE ? ESCAPE '\\' OR t.note LIKE ? ESCAPE '\\')")
        like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        args += [like, like]
    if category == "none":
        where.append("t.category_id IS NULL")
    elif category:
        where.append("t.category_id = ?")
        args.append(int(category))
    if account == "none":
        where.append("t.account_id IS NULL")
    elif account:
        where.append("t.account_id = ?")
        args.append(int(account))
    sql = _TX_SELECT
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY t.date DESC, t.id DESC"
    return get_db().execute(sql, args).fetchall()


def get_transaction(tx_id):
    return get_db().execute(_TX_SELECT + " WHERE t.id = ?", (tx_id,)).fetchone()


def insert_transaction(tx, commit=True):
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO transactions (date, amount_cents, payee, category_id, note,"
        " account_id) VALUES (?, ?, ?, ?, ?, ?)",
        (tx["date"], tx["amount_cents"], tx["payee"], tx.get("category_id"),
         tx.get("note", ""), tx.get("account_id")))
    if commit:
        conn.commit()
    return cur.lastrowid


def update_transaction(tx_id, tx):
    conn = get_db()
    cur = conn.execute(
        "UPDATE transactions SET date = ?, amount_cents = ?, payee = ?,"
        " category_id = ?, note = ?, account_id = ? WHERE id = ?",
        (tx["date"], tx["amount_cents"], tx["payee"], tx.get("category_id"),
         tx.get("note", ""), tx.get("account_id"), tx_id))
    conn.commit()
    return cur.rowcount > 0


def delete_transaction(tx_id):
    conn = get_db()
    cur = conn.execute("DELETE FROM transactions WHERE id = ?", (tx_id,))
    conn.commit()
    return cur.rowcount > 0


def uncategorised_transactions():
    return get_db().execute(
        "SELECT id, payee, amount_cents FROM transactions"
        " WHERE category_id IS NULL").fetchall()


def categorised_transactions():
    """Transactions that already have a category, newest first."""
    return get_db().execute(
        "SELECT t.id, t.date, t.payee, t.amount_cents, t.category_id,"
        " c.name AS category FROM transactions t"
        " JOIN categories c ON c.id = t.category_id"
        " ORDER BY t.date DESC, t.id DESC").fetchall()


def set_categories(pairs):
    """``pairs``: iterable of (category_id, transaction_id)."""
    conn = get_db()
    conn.executemany("UPDATE transactions SET category_id = ? WHERE id = ?", pairs)
    conn.commit()


def existing_keys(start, end, key):
    """Counter of ``key(date, amount_cents, payee)`` for transactions dated
    within [start, end] (inclusive), used for duplicate detection."""
    rows = get_db().execute(
        "SELECT date, amount_cents, payee FROM transactions"
        " WHERE date >= ? AND date <= ?", (start, end)).fetchall()
    return Counter(key(r["date"], r["amount_cents"], r["payee"]) for r in rows)


# --------------------------------------------------------------------- rules

def list_rules():
    return get_db().execute(
        "SELECT r.id, r.pattern, r.category_id, r.match_type,"
        " r.min_cents, r.max_cents, c.name AS category"
        " FROM rules r JOIN categories c ON c.id = r.category_id"
        " ORDER BY r.id").fetchall()


def add_rule(pattern, category_id, match_type="contains",
             min_cents=None, max_cents=None):
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO rules (pattern, category_id, match_type, min_cents, max_cents)"
        " VALUES (?, ?, ?, ?, ?)",
        (pattern, category_id, match_type, min_cents, max_cents))
    conn.commit()
    return cur.lastrowid


def delete_rule(rule_id):
    conn = get_db()
    cur = conn.execute("DELETE FROM rules WHERE id = ?", (rule_id,))
    conn.commit()
    return cur.rowcount > 0


# ------------------------------------------------------------------- budgets

def budgets_for_month(month):
    """Map category id -> (amount_cents, month the amount was set in).

    A budget set for a month carries forward to later months until a newer
    one is set, so you only enter it again when it changes."""
    rows = get_db().execute(
        "SELECT b.category_id, b.amount_cents, b.month FROM budgets b"
        " WHERE b.month = (SELECT MAX(month) FROM budgets"
        "                  WHERE category_id = b.category_id AND month <= ?)",
        (month,)).fetchall()
    return {r["category_id"]: (r["amount_cents"], r["month"]) for r in rows}


def set_budget(category_id, month, amount_cents):
    """Set (or with ``None`` clear) the budget explicitly set for ``month``."""
    conn = get_db()
    if amount_cents is None:
        conn.execute("DELETE FROM budgets WHERE category_id = ? AND month = ?",
                     (category_id, month))
    else:
        conn.execute(
            "INSERT INTO budgets (category_id, month, amount_cents) VALUES (?, ?, ?)"
            " ON CONFLICT (category_id, month) DO UPDATE SET amount_cents = excluded.amount_cents",
            (category_id, month, amount_cents))
    conn.commit()


# ------------------------------------------------------------------- reports

def category_net(month):
    """Rows of (category_id, category, net_cents, count) for one month.
    ``category_id`` is None for uncategorised transactions."""
    start, end = month_range(month)
    return get_db().execute(
        "SELECT t.category_id, c.name AS category,"
        "       SUM(t.amount_cents) AS net_cents, COUNT(*) AS count"
        " FROM transactions t LEFT JOIN categories c ON c.id = t.category_id"
        " WHERE t.date >= ? AND t.date < ?"
        " GROUP BY t.category_id ORDER BY net_cents", (start, end)).fetchall()


def month_totals(month):
    """(income_cents, expense_cents) for a month; both non-negative."""
    start, end = month_range(month)
    row = get_db().execute(
        "SELECT COALESCE(SUM(CASE WHEN amount_cents > 0 THEN amount_cents END), 0),"
        "       COALESCE(-SUM(CASE WHEN amount_cents < 0 THEN amount_cents END), 0)"
        " FROM transactions WHERE date >= ? AND date < ?", (start, end)).fetchone()
    return row[0], row[1]


# ----------------------------------------------------------- pending imports

def save_pending_import(filename, content):
    conn = get_db()
    conn.execute("DELETE FROM pending_imports WHERE created_at < datetime('now', '-1 day')")
    cur = conn.execute("INSERT INTO pending_imports (filename, content) VALUES (?, ?)",
                       (filename, content))
    conn.commit()
    return cur.lastrowid


def get_pending_import(import_id):
    return get_db().execute("SELECT id, filename, content FROM pending_imports WHERE id = ?",
                            (import_id,)).fetchone()


def delete_pending_import(import_id):
    conn = get_db()
    conn.execute("DELETE FROM pending_imports WHERE id = ?", (import_id,))
    conn.commit()


# ----------------------------------------------------------- import profiles

def header_key(header):
    """Identify a bank's export by its header row, ignoring case and spacing."""
    return json.dumps([" ".join(h.split()).casefold() for h in header])


def get_import_profile(header):
    row = get_db().execute(
        "SELECT id, name, mapping FROM import_profiles WHERE header_key = ?",
        (header_key(header),)).fetchone()
    if row is None:
        return None
    try:
        mapping = json.loads(row["mapping"])
    except ValueError:
        return None
    if not isinstance(mapping, dict):
        return None
    return {"id": row["id"], "name": row["name"], "mapping": mapping}


def save_import_profile(header, name, mapping):
    """Store (or replace) the column mapping used for files with this header."""
    conn = get_db()
    conn.execute(
        "INSERT INTO import_profiles (header_key, name, mapping) VALUES (?, ?, ?)"
        " ON CONFLICT (header_key) DO UPDATE SET mapping = excluded.mapping,"
        " updated_at = datetime('now')",
        (header_key(header), name, json.dumps(mapping, sort_keys=True)))
    conn.commit()


def category_usage():
    """Map category id -> number of transactions and rules."""
    conn = get_db()
    usage = {c["id"]: {"transactions": 0, "rules": 0} for c in list_categories()}
    for table, key in (("transactions", "transactions"), ("rules", "rules")):
        for r in conn.execute(f"SELECT category_id, COUNT(*) FROM {table}"
                              " WHERE category_id IS NOT NULL GROUP BY category_id"):
            if r[0] in usage:
                usage[r[0]][key] = r[1]
    return usage


def _profile_row(row):
    try:
        mapping = json.loads(row["mapping"])
        header = json.loads(row["header_key"])
    except ValueError:
        mapping, header = {}, []
    return {"id": row["id"], "name": row["name"], "updated_at": row["updated_at"],
            "header": header if isinstance(header, list) else [],
            "mapping": mapping if isinstance(mapping, dict) else {}}


def list_import_profiles():
    """Saved mappings, by name. ``header`` is the normalised header row."""
    rows = get_db().execute(
        "SELECT id, header_key, name, mapping, updated_at FROM import_profiles"
        " ORDER BY name COLLATE NOCASE, id").fetchall()
    return [_profile_row(r) for r in rows]


def get_import_profile_by_id(profile_id):
    row = get_db().execute(
        "SELECT id, header_key, name, mapping, updated_at FROM import_profiles"
        " WHERE id = ?", (profile_id,)).fetchone()
    return None if row is None else _profile_row(row)


def update_import_profile(profile_id, name, mapping):
    conn = get_db()
    conn.execute("UPDATE import_profiles SET name = ?, mapping = ?,"
                 " updated_at = datetime('now') WHERE id = ?",
                 (name, json.dumps(mapping, sort_keys=True), profile_id))
    conn.commit()


def delete_import_profile(profile_id):
    conn = get_db()
    cur = conn.execute("DELETE FROM import_profiles WHERE id = ?", (profile_id,))
    conn.commit()
    return cur.rowcount > 0
