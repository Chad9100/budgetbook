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
