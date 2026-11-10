import io
import re

from budgetbook import db

CSV = (
    "Buchungstag;Empfaenger;Soll;Haben;Info\n"
    "01.10.2026;REWE Markt;12,50;;card\n"
    "02.10.2026;Arbeitgeber GmbH;;2.000,00;\n"
)
MAPPING = {"date_col": "0", "date_fmt": "%d.%m.%Y", "mode": "split",
           "debit_col": "2", "credit_col": "3", "payee_col": "1",
           "note_col": "", "decimal": "comma", "remember": "1"}


def upload(post, name="dkb-october.csv"):
    r = post("/import", {"file": (io.BytesIO(CSV.encode()), name)},
             content_type="multipart/form-data")
    return r.headers["Location"]


def save_profile(post):
    assert post(upload(post), MAPPING).status_code == 200


def only_profile(app):
    with app.app_context():
        (profile,) = db.list_import_profiles()
        return profile


def selected(body, name):
    m = re.search(rf'name="{name}">(.*?)</select>', body, re.S)
    found = re.search(r'<option value="([^"]*)" selected', m.group(1))
    return found.group(1) if found else ""


def test_list_shows_saved_profiles(post, client):
    body = client.get("/import/profiles").get_data(as_text=True)
    assert "No saved mappings yet" in body
    save_profile(post)
    body = client.get("/import/profiles").get_data(as_text=True)
    assert "dkb-october" in body
    assert "buchungstag, empfaenger, soll, haben, info" in body
    assert "/import/profiles" in client.get("/import").get_data(as_text=True)


def test_edit_form_is_prefilled(post, client, app):
    save_profile(post)
    pid = only_profile(app)["id"]
    body = client.get(f"/import/profiles/{pid}").get_data(as_text=True)
    assert 'name="name" value="dkb-october"' in body
    assert selected(body, "date_fmt") == "%d.%m.%Y"
    assert selected(body, "debit_col") == "2" and selected(body, "credit_col") == "3"
    assert selected(body, "decimal") == "comma"
    assert re.search(r'name="mode" value="split" checked', body)


def test_rename_and_edit_mapping_is_used_on_next_upload(post, client, app):
    save_profile(post)
    pid = only_profile(app)["id"]
    r = post(f"/import/profiles/{pid}",
             {**MAPPING, "name": "  DKB   current ", "note_col": "4", "negate": "1"})
    assert r.status_code == 302
    assert only_profile(app)["name"] == "DKB current"
    body = client.get(upload(post, "dkb-november.csv")).get_data(as_text=True)
    assert "DKB current" in body
    assert selected(body, "note_col") == "4"
    assert 'name="negate" value="1" checked' in body
    # a later import with "remember" updates the mapping but keeps the new name
    post(upload(post, "dkb-december.csv"), MAPPING)
    assert only_profile(app)["name"] == "DKB current"
    assert only_profile(app)["mapping"]["note_col"] == ""


def test_invalid_edit_is_rejected(post, client, app):
    save_profile(post)
    profile = only_profile(app)
    pid = profile["id"]
    r = post(f"/import/profiles/{pid}", {**MAPPING, "name": "", "payee_col": "9",
                                         "date_fmt": "%s"})
    body = r.get_data(as_text=True)
    assert r.status_code == 400
    assert "Name is required." in body
    assert "The payee column is not in the file." in body
    assert "Choose a date format." in body
    assert only_profile(app) == profile


def test_delete_profile(post, client, app):
    save_profile(post)
    pid = only_profile(app)["id"]
    assert post(f"/import/profiles/{pid}/delete").status_code == 302
    with app.app_context():
        assert db.list_import_profiles() == []
    body = client.get(upload(post)).get_data(as_text=True)
    assert "mapping you saved" not in body
    assert post(f"/import/profiles/{pid}/delete").status_code == 404


def test_missing_profile_is_404(post, client):
    assert client.get("/import/profiles/99").status_code == 404
    assert post("/import/profiles/99", {**MAPPING, "name": "x"}).status_code == 404


def test_profile_routes_require_csrf(post, client, app):
    save_profile(post)
    pid = only_profile(app)["id"]
    assert client.post(f"/import/profiles/{pid}/delete").status_code == 400
    assert client.post(f"/import/profiles/{pid}", data={**MAPPING, "name": "x"}).status_code == 400
    assert only_profile(app)["name"] == "dkb-october"
