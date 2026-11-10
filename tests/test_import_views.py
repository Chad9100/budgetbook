import io
import re

from budgetbook import db

BANK_CSV = (
    "﻿Date,Description,Amount,Reference\n"
    "2026-10-01,TESCO STORES 1234,-23.45,card\n"
    "2026-10-02,Employer Ltd,2500.00,salary\n"
    "2026-10-03,Coffee <Bar>,-3.20,\n"
)


def upload(post, text, name="bank.csv"):
    data = {"file": (io.BytesIO(text.encode("utf-8")), name)}
    return post("/import", data, content_type="multipart/form-data")


def import_id(response):
    return int(re.search(r"/import/(\d+)$", response.headers["Location"]).group(1))


MAPPING = {"date_col": "0", "date_fmt": "%Y-%m-%d", "mode": "single",
           "amount_col": "2", "payee_col": "1", "note_col": "3", "decimal": "dot"}


def test_upload_shows_mapping_step_with_guesses(post, client):
    r = upload(post, BANK_CSV)
    assert r.status_code == 302
    body = client.get(r.headers["Location"]).get_data(as_text=True)
    assert "bank.csv" in body and "3 rows" in body
    assert "Coffee &lt;Bar&gt;" in body
    # guessed columns are preselected
    assert re.search(r'name="date_col">.*?<option value="0" selected', body, re.S)
    assert re.search(r'name="amount_col">.*?<option value="2" selected', body, re.S)
    assert re.search(r'name="payee_col">.*?<option value="0" >.*?<option value="1" selected', body, re.S)
    assert '<option value="%Y-%m-%d" selected' in body


def test_import_commits_rows_and_applies_rules(post, client, category, txs):
    groceries = category("Groceries")
    post("/rules", {"pattern": "tesco", "category_id": str(groceries)})
    iid = import_id(upload(post, BANK_CSV))
    r = post(f"/import/{iid}", MAPPING)
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "imported 3 transactions" in body and "(1 categorised by rules)" in body
    stored = txs()
    assert [(t["date"], t["amount_cents"], t["payee"], t["note"]) for t in stored] == [
        ("2026-10-01", -2345, "TESCO STORES 1234", "card"),
        ("2026-10-02", 250000, "Employer Ltd", "salary"),
        ("2026-10-03", -320, "Coffee <Bar>", ""),
    ]
    assert stored[0]["category_id"] == groceries
    # the pending upload is gone once committed
    assert client.get(f"/import/{iid}").status_code == 404


def test_reimporting_overlapping_statement_skips_duplicates(post, txs):
    post(f"/import/{import_id(upload(post, BANK_CSV))}", MAPPING)
    overlap = BANK_CSV + "2026-10-04,Bus,-2.00,\n"
    r = post(f"/import/{import_id(upload(post, overlap))}", MAPPING)
    body = r.get_data(as_text=True)
    assert re.search(r"imported 1 transaction\b(?!s)", body) and "skipped 3 duplicates" in body
    assert len(txs()) == 4


def test_allow_duplicates_imports_everything(post, txs):
    post(f"/import/{import_id(upload(post, BANK_CSV))}", MAPPING)
    post(f"/import/{import_id(upload(post, BANK_CSV))}", {**MAPPING, "allow_duplicates": "1"})
    assert len(txs()) == 6


def test_bad_rows_are_reported_and_good_rows_imported(post, txs):
    text = "Date,Payee,Amount\n2026-10-01,Ok,-1.00\n31/10/2026,Bad date,-1\n2026-10-02,Bad amount,abc\n"
    r = post(f"/import/{import_id(upload(post, text))}",
             {"date_col": "0", "date_fmt": "%Y-%m-%d", "amount_col": "2", "payee_col": "1"})
    body = r.get_data(as_text=True)
    assert re.search(r"imported 1 transaction\b(?!s)", body) and "2 rows with errors" in body
    assert "line 3: date &#39;31/10/2026&#39; does not match" in body
    assert "line 4: not a valid amount" in body
    assert len(txs()) == 1


def test_wrong_mapping_keeps_upload_for_another_try(post, client, txs):
    iid = import_id(upload(post, BANK_CSV))
    r = post(f"/import/{iid}", {**MAPPING, "date_fmt": "%d/%m/%Y"})
    assert r.status_code == 400
    assert "No row could be imported" in r.get_data(as_text=True)
    assert txs() == []
    assert client.get(f"/import/{iid}").status_code == 200
    r = post(f"/import/{iid}", {**MAPPING, "amount_col": ""})
    assert r.status_code == 400 and "Choose the amount column." in r.get_data(as_text=True)


def test_split_debit_credit_semicolon_csv(post, txs):
    text = ("Datum;Omschrijving;Af;Bij\n"
            "01-10-2026;Huur;1.150,00;\n"
            "25-10-2026;Salaris;;3.000,00\n")
    r = post(f"/import/{import_id(upload(post, text))}", {
        "date_col": "0", "date_fmt": "%d-%m-%Y", "mode": "split", "debit_col": "2",
        "credit_col": "3", "payee_col": "1", "decimal": "comma"})
    assert r.status_code == 200
    assert [(t["date"], t["amount_cents"]) for t in txs()] == [
        ("2026-10-01", -115000), ("2026-10-25", 300000)]


def test_upload_errors(post, client):
    assert post("/import", {}, content_type="multipart/form-data").status_code == 400
    r = upload(post, "Date,Amount,Payee\n")
    assert r.status_code == 400 and "no transactions" in r.get_data(as_text=True)
    assert upload(post, "\n\n").status_code == 400
    assert client.get("/import/12345").status_code == 404


def test_cp1252_file_is_decoded(post, txs, app):
    raw = "Date,Payee,Amount\n2026-10-01,Caf\xe9 Rouge,-4.00\n".encode("cp1252")
    r = post("/import", {"file": (io.BytesIO(raw), "old.csv")},
             content_type="multipart/form-data")
    post(f"/import/{import_id(r)}", {"date_col": "0", "date_fmt": "%Y-%m-%d",
                                     "amount_col": "2", "payee_col": "1"})
    assert txs()[0]["payee"] == "Café Rouge"
    with app.app_context():
        assert db.get_db().execute("SELECT COUNT(*) FROM pending_imports").fetchone()[0] == 0


def test_example_statement_imports_with_guessed_mapping(post, client, txs):
    from pathlib import Path
    raw = (Path(__file__).parent.parent / "examples" / "bank-statement.csv").read_bytes()
    r = post("/import", {"file": (io.BytesIO(raw), "bank-statement.csv")},
             content_type="multipart/form-data")
    page = client.get(r.headers["Location"]).get_data(as_text=True)
    form = {name: value for name, value in
            re.findall(r'name="(\w+_col|date_fmt)">(?:(?!</select>).)*?<option value="([^"]*)" selected',
                       page, re.S)}
    assert form == {"date_col": "0", "date_fmt": "%Y-%m-%d", "amount_col": "2",
                    "payee_col": "1", "note_col": "3"}
    body = post(f"/import/{import_id(r)}", {**form, "mode": "single"}).get_data(as_text=True)
    assert "imported 13 transactions" in body
    assert sum(t["amount_cents"] for t in txs()) == 285000 - 95000 - 4217 - 3840 - 1099 - 865 - 620 - 6130 - 5502 - 1450 - 2399 + 999 - 480


# ---------------------------------------------------------- saved profiles

SEMICOLON_CSV = (
    "Buchungstag;Empfaenger;Soll;Haben\n"
    "01.10.2026;REWE Markt;12,50;\n"
    "02.10.2026;Arbeitgeber GmbH;;2.000,00\n"
)
SEMICOLON_MAPPING = {"date_col": "0", "date_fmt": "%d.%m.%Y", "mode": "split",
                     "debit_col": "2", "credit_col": "3", "payee_col": "1",
                     "note_col": "", "decimal": "comma", "remember": "1"}


def selected(body, name):
    m = re.search(rf'name="{name}">(.*?)</select>', body, re.S)
    found = re.search(r'<option value="([^"]*)" selected', m.group(1))
    return found.group(1) if found else ""


def test_mapping_is_remembered_and_preselected_for_same_header(post, client, txs):
    r = post(f"/import/{import_id(upload(post, SEMICOLON_CSV, 'dkb-october.csv'))}",
             SEMICOLON_MAPPING)
    assert r.status_code == 200 and len(txs()) == 2
    # next month's statement has the same columns (header case/spacing differ)
    again = SEMICOLON_CSV.replace("Buchungstag", "BUCHUNGSTAG ").replace("10.2026", "11.2026")
    body = client.get(upload(post, again, "dkb-november.csv").headers["Location"]).get_data(as_text=True)
    assert "mapping you saved for this bank" in body and "dkb-october" in body
    assert selected(body, "date_col") == "0"
    assert selected(body, "date_fmt") == "%d.%m.%Y"
    assert selected(body, "debit_col") == "2" and selected(body, "credit_col") == "3"
    assert selected(body, "decimal") == "comma"
    assert re.search(r'name="mode" value="split" checked', body)
    assert 'name="remember" value="1" checked' in body


def test_without_remember_nothing_is_saved(post, client):
    data = dict(SEMICOLON_MAPPING)
    del data["remember"]
    post(f"/import/{import_id(upload(post, SEMICOLON_CSV))}", data)
    body = client.get(upload(post, SEMICOLON_CSV).headers["Location"]).get_data(as_text=True)
    assert "mapping you saved" not in body
    assert selected(body, "decimal") == "dot"


def test_different_header_falls_back_to_guesses(post, client):
    post(f"/import/{import_id(upload(post, SEMICOLON_CSV))}", SEMICOLON_MAPPING)
    body = client.get(upload(post, BANK_CSV).headers["Location"]).get_data(as_text=True)
    assert "mapping you saved" not in body
    assert selected(body, "amount_col") == "2"


def test_saving_again_updates_the_profile(post, client):
    post(f"/import/{import_id(upload(post, BANK_CSV))}", {**MAPPING, "remember": "1"})
    post(f"/import/{import_id(upload(post, BANK_CSV))}",
         {**MAPPING, "note_col": "", "negate": "1", "remember": "1",
          "allow_duplicates": "1"})
    body = client.get(upload(post, BANK_CSV).headers["Location"]).get_data(as_text=True)
    assert selected(body, "note_col") == ""
    assert 'name="negate" value="1" checked' in body
    # allow_duplicates is a per-import choice, never remembered
    assert 'name="allow_duplicates" value="1" checked' not in body


def test_stale_or_malformed_profile_values_are_ignored(app, post, client):
    with app.app_context():
        conn = db.get_db()
        conn.execute("INSERT INTO import_profiles (header_key, name, mapping) VALUES (?, ?, ?)",
                     (db.header_key(["Date", "Description", "Amount", "Reference"]), "old",
                      '{"date_col": "9", "amount_col": "x", "date_fmt": "%s", "payee_col": "3"}'))
        conn.commit()
    body = client.get(upload(post, BANK_CSV).headers["Location"]).get_data(as_text=True)
    assert selected(body, "date_col") == "0"      # out of range -> guess
    assert selected(body, "amount_col") == "2"    # not a number -> guess
    assert selected(body, "payee_col") == "3"     # valid saved value wins
    assert '<option value="%Y-%m-%d" selected' in body


def test_failed_import_does_not_save_profile(post, client):
    iid = import_id(upload(post, BANK_CSV))
    r = post(f"/import/{iid}", {**MAPPING, "date_fmt": "%d/%m/%Y", "remember": "1"})
    assert r.status_code == 400
    body = client.get(upload(post, BANK_CSV).headers["Location"]).get_data(as_text=True)
    assert "mapping you saved" not in body


def test_version_1_database_is_upgraded_in_place(tmp_path):
    import sqlite3

    from budgetbook import create_app

    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE categories (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE);"
        "CREATE TABLE transactions (id INTEGER PRIMARY KEY, date TEXT NOT NULL,"
        " amount_cents INTEGER NOT NULL, payee TEXT NOT NULL, category_id INTEGER,"
        " note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT (datetime('now')));"
        "INSERT INTO transactions (date, amount_cents, payee) VALUES ('2026-10-01', -500, 'Kept');"
        "PRAGMA user_version = 1;")
    conn.close()
    app = create_app({"TESTING": True, "SECRET_KEY": "t", "DATABASE": str(path)})
    with app.app_context():
        assert [t["payee"] for t in db.list_transactions()] == ["Kept"]
        assert db.get_import_profile(["Date"]) is None
        db.save_import_profile(["Date"], "x", {"date_col": "0"})
        assert db.get_import_profile([" date "])["mapping"] == {"date_col": "0"}
    conn = sqlite3.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    conn.close()
