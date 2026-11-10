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


def test_amount_range_limits_a_rule_and_ignores_sign():
    big = ("amazon", 1, "contains", 10000, None)
    small = ("amazon", 2, "contains", None, 999)
    assert pick_category("Amazon", [big], -15000) == 1
    assert pick_category("Amazon", [big], 15000) == 1
    assert pick_category("Amazon", [big], -9999) is None
    assert pick_category("Amazon", [big], 10000) == 1
    assert pick_category("Amazon", [small], -999) == 2
    assert pick_category("Amazon", [small], -1000) is None
    # unknown amount only matches rules without a range
    assert pick_category("Amazon", [big]) is None
    assert pick_category("Amazon", [("amazon", 3)]) == 3


def test_ranged_rule_beats_plain_rule_of_same_rank():
    rules = [("amazon", 1, "contains", None, None),
             ("amazon", 2, "contains", 5000, None)]
    assert pick_category("Amazon", rules, -6000) == 2
    assert pick_category("Amazon", rules, -1000) == 1


def test_rules_view_amount_range_validation_and_use(post, client, category, add_tx, txs):
    big, small = category("Big shop"), category("Top-up")
    for bad in ({"min_amount": "abc"}, {"max_amount": "-5"},
                {"min_amount": "50", "max_amount": "10"}):
        r = post("/rules", {"pattern": "tesco", "category_id": str(big), **bad})
        assert r.status_code == 400
    r = post("/rules", {"pattern": "tesco", "category_id": str(big),
                        "min_amount": "100"}, follow_redirects=True)
    body = r.get_data(as_text=True)
    assert "for amounts of 100.00 or more" in body and "<td>for amounts of 100.00 or more</td>" in body
    post("/rules", {"pattern": "tesco", "category_id": str(small), "max_amount": "99.99"})

    add_tx(payee="TESCO", amount="150.00")
    add_tx(payee="TESCO", amount="12.50")
    add_tx(payee="TESCO", amount="99.99")
    assert [t["category_id"] for t in txs()] == [big, small, small]


def test_apply_rules_uses_amounts_and_csrf(client, post, category, add_tx, txs):
    cat = category("Large")
    add_tx(payee="Garage", amount="500.00")
    add_tx(payee="Garage", amount="20.00")
    post("/rules", {"pattern": "garage", "category_id": str(cat), "min_amount": "100"})
    post("/rules/apply", {})
    assert [t["category_id"] for t in txs()] == [cat, None]
    assert client.post("/rules", data={"pattern": "x", "category_id": str(cat),
                                       "min_amount": "1"}).status_code == 400


def test_make_rule_link_prefills_form_from_transaction(client, category, add_tx, txs):
    fuel = category("Fuel")
    add_tx(payee="  Shell   Garage <1>", category_id=fuel)
    add_tx(payee="Cinema")
    first, second = [t["id"] for t in txs()]
    assert f"/rules?from_tx={first}" in client.get("/").get_data(as_text=True)

    body = client.get(f"/rules?from_tx={first}").get_data(as_text=True)
    assert 'value="Shell Garage &lt;1&gt;"' in body
    assert f'<option value="{fuel}" selected' in body
    body = client.get(f"/rules?from_tx={second}").get_data(as_text=True)
    assert 'value="Cinema"' in body
    assert "selected" not in body.split('name="category_id"')[1].split("</select>")[0]
    assert client.get("/rules?from_tx=9999").status_code == 404


def test_version_3_database_gains_amount_columns(tmp_path):
    import sqlite3

    from budgetbook import create_app, db

    path = tmp_path / "v3.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE categories (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE);"
        "CREATE TABLE rules (id INTEGER PRIMARY KEY, pattern TEXT NOT NULL,"
        " category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,"
        " match_type TEXT NOT NULL DEFAULT 'contains');"
        "INSERT INTO categories (id, name) VALUES (1, 'Groceries');"
        "INSERT INTO rules (pattern, category_id, match_type) VALUES ('tesco', 1, 'exact');"
        "PRAGMA user_version = 3;")
    conn.close()
    app = create_app({"TESTING": True, "SECRET_KEY": "t", "DATABASE": str(path)})
    with app.app_context():
        (rule,) = db.list_rules()
        assert (rule["match_type"], rule["min_cents"], rule["max_cents"]) == ("exact", None, None)
        db.add_rule("aldi", 1, "contains", 500, 9000)
        assert db.list_rules()[1]["max_cents"] == 9000
    create_app({"TESTING": True, "SECRET_KEY": "t", "DATABASE": str(path)})
    conn = sqlite3.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 4
    conn.close()


def test_reapply_preview_and_apply_selected(client, post, category, add_tx, txs):
    food, fuel = category("Food"), category("Fuel")
    add_tx(payee="Shell Garage", category_id=food)   # wrong category
    add_tx(payee="Tesco", category_id=food)          # already right
    add_tx(payee="Unknown", category_id=food)        # no rule matches
    post("/rules", {"pattern": "shell", "category_id": str(fuel)})
    post("/rules", {"pattern": "tesco", "category_id": str(food)})

    body = client.get("/rules/reapply").get_data(as_text=True)
    assert "Shell Garage" in body and "Tesco" not in body and "Unknown" not in body
    # preview alone changes nothing
    assert [t["category_id"] for t in txs()] == [food, food, food]

    shell_id = txs()[0]["id"]
    assert client.post("/rules/reapply", data={"tx_id": str(shell_id)}).status_code == 400
    post("/rules/reapply", {"tx_id": []})
    assert txs()[0]["category_id"] == food          # nothing ticked
    r = post("/rules/reapply", {"tx_id": [str(shell_id), "9999"]}, follow_redirects=True)
    assert "Recategorised 1 transaction." in r.get_data(as_text=True)
    assert [t["category_id"] for t in txs()] == [fuel, food, food]
    assert "Nothing to change" in client.get("/rules/reapply").get_data(as_text=True)
