import json
import sqlite3

from budgetbook.cli import main


def _populate(path):
    main(["init", "--db", str(path), "--no-categories"])
    c = sqlite3.connect(path)
    c.execute("INSERT INTO categories (id, name) VALUES (7, 'Groceries'), (9, 'Café')")
    c.execute("INSERT INTO accounts (id, name, kind, opening_cents) VALUES (3, 'Main', 'current', 10000)")
    c.execute("INSERT INTO rules (pattern, category_id, match_type, min_cents) VALUES ('shop', 7, 'starts', -5000)")
    c.execute("INSERT INTO budgets VALUES (7, '2025-01', 30000)")
    c.execute("INSERT INTO transactions (date, amount_cents, payee, category_id, note, account_id)"
              " VALUES ('2025-01-02', -450, 'Café Ünï', 9, 'latte', 3),"
              " ('2025-01-03', -1200, 'Shop', 7, '', NULL),"
              " ('2025-01-04', -99, 'Loose', NULL, '', NULL)")
    c.commit()
    c.close()


def _dump(path):
    c = sqlite3.connect(path)
    out = {
        "tx": c.execute("SELECT t.date, t.amount_cents, t.payee, c.name, t.note, a.name"
                        " FROM transactions t LEFT JOIN categories c ON c.id = t.category_id"
                        " LEFT JOIN accounts a ON a.id = t.account_id ORDER BY t.date").fetchall(),
        "rules": c.execute("SELECT pattern, match_type, min_cents, max_cents FROM rules").fetchall(),
        "budgets": c.execute("SELECT amount_cents, month FROM budgets").fetchall(),
        "acct": c.execute("SELECT name, opening_cents FROM accounts").fetchall(),
    }
    c.close()
    return out


def test_roundtrip_to_fresh_database_with_different_ids(tmp_path, capsys):
    src, dest, js = tmp_path / "a.db", tmp_path / "b.db", tmp_path / "all.json"
    _populate(src)
    assert main(["export", "--json", "--db", str(src), "--out", str(js)]) == 0
    assert "Exported 3 transactions" in capsys.readouterr().out
    assert main(["import", "--json", str(js), "--db", str(dest)]) == 0
    assert _dump(dest) == _dump(src)
    assert "Café Ünï" in js.read_text(encoding="utf-8")


def test_export_to_stdout_is_valid_json(tmp_path, capsys):
    src = tmp_path / "a.db"
    _populate(src)
    capsys.readouterr()
    assert main(["export", "--json", "--db", str(src)]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["format"] == "budgetbook-export" and len(data["transactions"]) == 3
    assert data["categories"] == ["Groceries", "Café"]


def test_import_twice_adds_nothing_the_second_time(tmp_path, capsys):
    src, dest, js = tmp_path / "a.db", tmp_path / "b.db", tmp_path / "all.json"
    _populate(src)
    main(["export", "--json", "--db", str(src), "--out", str(js)])
    main(["import", "--json", str(js), "--db", str(dest)])
    before = _dump(dest)
    capsys.readouterr()
    assert main(["import", "--json", str(js), "--db", str(dest)]) == 0
    out = capsys.readouterr().out
    assert "transactions  0 added, 3 already present" in out
    assert _dump(dest) == before


def test_import_merges_into_existing_data_by_name(tmp_path):
    src, dest, js = tmp_path / "a.db", tmp_path / "b.db", tmp_path / "all.json"
    _populate(src)
    main(["export", "--json", "--db", str(src), "--out", str(js)])
    main(["init", "--db", str(dest), "--no-categories"])
    c = sqlite3.connect(dest)
    c.execute("INSERT INTO categories (id, name) VALUES (1, 'groceries')")
    c.commit()
    c.close()
    assert main(["import", "--json", str(js), "--db", str(dest)]) == 0
    c = sqlite3.connect(dest)
    assert c.execute("SELECT COUNT(*) FROM categories").fetchone()[0] == 2
    assert c.execute("SELECT c.name FROM transactions t JOIN categories c ON c.id = t.category_id"
                     " WHERE payee = 'Shop'").fetchone()[0] == "groceries"
    c.close()


def test_import_rejects_bad_files_without_changing_db(tmp_path, capsys):
    db = tmp_path / "b.db"
    bad = tmp_path / "bad.json"
    for text, msg in [("{nope", "cannot read"),
                      ('{"format": "other"}', "not a budgetbook export"),
                      (json.dumps({"format": "budgetbook-export", "version": 9}), "unsupported"),
                      (json.dumps({"format": "budgetbook-export", "version": 1, "categories": [],
                                   "accounts": [], "rules": [], "budgets": [],
                                   "transactions": [{"date": "2025-01-01"}]}), "transaction 1"),
                      (json.dumps({"format": "budgetbook-export", "version": 1, "categories": ["X"],
                                   "accounts": [], "rules": [{"pattern": "p"}], "budgets": [],
                                   "transactions": []}), "invalid export file")]:
        bad.write_text(text, encoding="utf-8")
        assert main(["import", "--json", str(bad), "--db", str(db)]) == 1
        assert msg in capsys.readouterr().err
    c = sqlite3.connect(db)
    assert c.execute("SELECT COUNT(*) FROM categories").fetchone()[0] == 0  # rolled back
    c.close()


def test_import_missing_file_and_export_missing_db(tmp_path, capsys):
    assert main(["import", "--json", str(tmp_path / "none.json"), "--db", str(tmp_path / "x.db")]) == 1
    assert "cannot read" in capsys.readouterr().err
    assert main(["export", "--json", "--db", str(tmp_path / "none.db")]) == 1
    assert "no database" in capsys.readouterr().err
    assert not (tmp_path / "none.db").exists()
