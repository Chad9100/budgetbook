from budgetbook.rules import pick_category


def test_pick_category_is_case_insensitive_substring():
    rules = [("tesco", 1), ("shell", 2)]
    assert pick_category("TESCO STORES 1234", rules) == 1
    assert pick_category("Shell Garage", rules) == 2
    assert pick_category("Amazon", rules) is None


def test_longest_pattern_wins_and_ties_go_to_first():
    rules = [("amazon", 1), ("amazon prime", 2), ("prime", 3), ("amazon", 4)]
    assert pick_category("AMAZON PRIME VIDEO", rules) == 2
    assert pick_category("amazon.co.uk", rules) == 1


def test_whitespace_is_normalised_and_blank_patterns_ignored():
    rules = [("  ", 9), ("corner  shop", 5)]
    assert pick_category("The Corner   Shop", rules) == 5
    assert pick_category("anything", [("", 9)]) is None


def test_rules_view_add_apply_and_delete(post, client, category, add_tx, txs):
    groceries = category("Groceries")
    add_tx(payee="TESCO 123")
    add_tx(payee="Cinema")
    assert txs()[0]["category_id"] is None

    r = post("/rules", {"pattern": "tesco", "category_id": str(groceries)})
    assert r.status_code == 302
    assert "tesco" in client.get("/rules").get_data(as_text=True)

    r = post("/rules/apply", follow_redirects=True)
    assert "Categorised 1 transaction." in r.get_data(as_text=True)
    assert [t["category_id"] for t in txs()] == [groceries, None]

    # new transactions without a category are categorised on save
    add_tx(payee="tesco express")
    assert txs()[-1]["category_id"] == groceries

    from budgetbook import db
    with client.application.app_context():
        rule_id = db.list_rules()[0]["id"]
    assert post(f"/rules/{rule_id}/delete").status_code == 302
    assert post(f"/rules/{rule_id}/delete").status_code == 404


def test_rules_view_validation(post, category):
    category("Fun")
    r = post("/rules", {"pattern": "", "category_id": "999"})
    assert r.status_code == 400
    body = r.get_data(as_text=True)
    assert "Pattern is required." in body and "Unknown category." in body


def test_starts_with_and_exact_match_types():
    rules = [("shell", 1, "starts"), ("corner shop", 2, "exact")]
    assert pick_category("SHELL Garage", rules) == 1
    assert pick_category("The Shell Garage", rules) is None
    assert pick_category("Corner   SHOP", rules) == 2
    assert pick_category("Corner Shop Ltd", rules) is None


def test_regex_match_type_is_case_insensitive_search():
    rules = [(r"^amzn\s*mktp", 1, "regex"), (r"uber\s+(eats|trip)", 2, "regex")]
    assert pick_category("AMZN Mktp UK*123", rules) == 1
    assert pick_category("UBER  EATS london", rules) == 2
    assert pick_category("Uber One", rules) is None
    # an invalid stored pattern is skipped instead of raising
    assert pick_category("anything", [("(", 3, "regex")]) is None


def test_precedence_exact_then_longest_text_then_regex():
    rules = [(r"tesco", 1, "regex"), ("tes", 2, "contains"),
             ("tesco stores", 3, "starts"), ("tesco stores 1234", 4, "exact")]
    assert pick_category("Tesco Stores 1234", rules) == 4
    assert pick_category("Tesco Stores 99", rules) == 3
    assert pick_category("tesco", rules) == 2
    assert pick_category("xtesco", [(r"tesco", 1, "regex"), (r"t", 5, "regex")]) == 1


def test_rules_view_match_types_and_regex_validation(post, client, category, add_tx, txs):
    fuel = category("Fuel")
    r = post("/rules", {"match_type": "regex", "pattern": "shell (", "category_id": str(fuel)})
    assert r.status_code == 400
    body = r.get_data(as_text=True)
    assert "Invalid regular expression" in body
    assert 'value="shell ("' in body and '<option value="regex" selected' in body

    r = post("/rules", {"match_type": "fuzzy", "pattern": "x", "category_id": str(fuel)})
    assert r.status_code == 400 and "Unknown match type." in r.get_data(as_text=True)

    r = post("/rules", {"match_type": "regex", "pattern": r"^(shell|bp)\b",
                        "category_id": str(fuel)}, follow_redirects=True)
    body = r.get_data(as_text=True)
    assert "Rule added: payee matches regex" in body and "<td>matches regex</td>" in body

    add_tx(payee="BP Express")
    add_tx(payee="Shell Garage")
    add_tx(payee="BPX Shop")
    assert [t["category_id"] for t in txs()] == [fuel, fuel, None]


def test_rule_without_csrf_token_is_rejected(client, category):
    fuel = category("Fuel")
    r = client.post("/rules", data={"match_type": "exact", "pattern": "bp",
                                    "category_id": str(fuel)})
    assert r.status_code == 400


def test_version_2_database_rules_become_contains_rules(tmp_path):
    import sqlite3

    from budgetbook import create_app, db

    path = tmp_path / "v2.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE categories (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE);"
        "CREATE TABLE rules (id INTEGER PRIMARY KEY, pattern TEXT NOT NULL,"
        " category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE);"
        "INSERT INTO categories (id, name) VALUES (1, 'Groceries');"
        "INSERT INTO rules (pattern, category_id) VALUES ('tesco', 1);"
        "PRAGMA user_version = 2;")
    conn.close()
    app = create_app({"TESTING": True, "SECRET_KEY": "t", "DATABASE": str(path)})
    with app.app_context():
        rules = db.list_rules()
        assert [(r["pattern"], r["match_type"]) for r in rules] == [("tesco", "contains")]
        assert pick_category("TESCO EXPRESS", [(r["pattern"], r["category_id"], r["match_type"])
                                               for r in rules]) == 1
        db.add_rule("aldi", 1, "exact")
        assert db.list_rules()[1]["match_type"] == "exact"
    # opening it again does not try to add the column twice
    create_app({"TESTING": True, "SECRET_KEY": "t", "DATABASE": str(path)})
    conn = sqlite3.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    conn.close()
