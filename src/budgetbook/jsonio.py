"""Move a whole budgetbook between machines as one JSON document.

Rows refer to categories and accounts by name, not by id, so the file can be
imported into a database whose ids differ."""
from . import db

FORMAT = "budgetbook-export"
VERSION = 1


class ImportError_(ValueError):
    """The JSON file is not a valid budgetbook export."""


def export_data(conn):
    q = lambda sql: [dict(r) for r in conn.execute(sql)]
    return {
        "format": FORMAT,
        "version": VERSION,
        "categories": [r["name"] for r in conn.execute("SELECT name FROM categories ORDER BY id")],
        "accounts": q("SELECT name, kind, opening_cents FROM accounts ORDER BY id"),
        "rules": q("SELECT r.pattern, c.name AS category, r.match_type, r.min_cents,"
                   " r.max_cents FROM rules r JOIN categories c ON c.id = r.category_id"
                   " ORDER BY r.id"),
        "budgets": q("SELECT c.name AS category, b.month, b.amount_cents FROM budgets b"
                     " JOIN categories c ON c.id = b.category_id ORDER BY c.name, b.month"),
        "transactions": q("SELECT t.date, t.amount_cents, t.payee, t.note,"
                          " c.name AS category, a.name AS account FROM transactions t"
                          " LEFT JOIN categories c ON c.id = t.category_id"
                          " LEFT JOIN accounts a ON a.id = t.account_id"
                          " ORDER BY t.date, t.id"),
    }


def _need(cond, msg):
    if not cond:
        raise ImportError_(msg)


def _validate(data):
    _need(isinstance(data, dict) and data.get("format") == FORMAT,
          "not a budgetbook export file")
    _need(data.get("version") == VERSION,
          f"unsupported export version {data.get('version')!r}")
    for key in ("categories", "accounts", "rules", "budgets", "transactions"):
        _need(isinstance(data.get(key), list), f"'{key}' must be a list")
    for i, t in enumerate(data["transactions"], 1):
        _need(isinstance(t, dict) and isinstance(t.get("date"), str)
              and isinstance(t.get("amount_cents"), int)
              and not isinstance(t.get("amount_cents"), bool)
              and isinstance(t.get("payee"), str),
              f"transaction {i}: needs date, integer amount_cents and payee")


def import_data(conn, data):
    """Merge ``data`` into the open database in one transaction. Existing
    categories and accounts are matched by name; rules, budgets and
    transactions that are already present are skipped. Returns a dict of
    added/skipped counts."""
    _validate(data)
    added = dict.fromkeys(("categories", "accounts", "rules", "budgets", "transactions"), 0)
    skipped = dict.fromkeys(added, 0)
    try:
        cats = {r["name"].lower(): r["id"] for r in conn.execute("SELECT id, name FROM categories")}

        def cat_id(name, create=True):
            if not name:
                return None
            key = name.lower()
            if key not in cats:
                cats[key] = conn.execute("INSERT INTO categories (name) VALUES (?)",
                                         (name,)).lastrowid
                added["categories"] += 1
            return cats[key]

        known = set(cats)
        for name in data["categories"]:
            if name.lower() in known:
                skipped["categories"] += 1
            else:
                cat_id(name)
        accts = {r["name"].lower(): r["id"] for r in conn.execute("SELECT id, name FROM accounts")}
        for a in data["accounts"]:
            if a["name"].lower() in accts:
                skipped["accounts"] += 1
            else:
                accts[a["name"].lower()] = conn.execute(
                    "INSERT INTO accounts (name, kind, opening_cents) VALUES (?, ?, ?)",
                    (a["name"], a.get("kind", "current"), a.get("opening_cents", 0))).lastrowid
                added["accounts"] += 1
        for r in data["rules"]:
            row = (r["pattern"], cat_id(r["category"]), r.get("match_type", "contains"),
                   r.get("min_cents"), r.get("max_cents"))
            if conn.execute("SELECT 1 FROM rules WHERE pattern = ? AND category_id = ?"
                            " AND match_type = ? AND min_cents IS ? AND max_cents IS ?",
                            row).fetchone():
                skipped["rules"] += 1
            else:
                conn.execute("INSERT INTO rules (pattern, category_id, match_type,"
                             " min_cents, max_cents) VALUES (?, ?, ?, ?, ?)", row)
                added["rules"] += 1
        for b in data["budgets"]:
            cid = cat_id(b["category"])
            if conn.execute("SELECT 1 FROM budgets WHERE category_id = ? AND month = ?",
                            (cid, b["month"])).fetchone():
                skipped["budgets"] += 1
            else:
                conn.execute("INSERT INTO budgets (category_id, month, amount_cents)"
                             " VALUES (?, ?, ?)", (cid, b["month"], b["amount_cents"]))
                added["budgets"] += 1
        for t in data["transactions"]:
            cid = cat_id(t.get("category"))
            aid = accts.get((t.get("account") or "").lower())
            note = t.get("note", "")
            if conn.execute("SELECT 1 FROM transactions WHERE date = ? AND amount_cents = ?"
                            " AND payee = ? AND note = ? AND account_id IS ?",
                            (t["date"], t["amount_cents"], t["payee"], note, aid)).fetchone():
                skipped["transactions"] += 1
            else:
                conn.execute("INSERT INTO transactions (date, amount_cents, payee,"
                             " category_id, note, account_id) VALUES (?, ?, ?, ?, ?, ?)",
                             (t["date"], t["amount_cents"], t["payee"], cid, note, aid))
                added["transactions"] += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return added, skipped
