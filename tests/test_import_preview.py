import io
import re

from budgetbook import db

BANK_CSV = (
    "Date,Description,Amount,Reference\n"
    "2026-10-01,TESCO STORES 1234,-23.45,card\n"
    "2026-10-02,Employer Ltd,2500.00,salary\n"
    "2026-10-03,Coffee <Bar>,-3.20,\n"
    "2026-10-04,Broken row,abc,\n"
)

MAPPING = {"date_col": "0", "date_fmt": "%Y-%m-%d", "mode": "single",
           "amount_col": "2", "payee_col": "1", "note_col": "3", "decimal": "dot"}


def upload(post, text, name="bank.csv"):
    data = {"file": (io.BytesIO(text.encode("utf-8")), name)}
    r = post("/import", data, content_type="multipart/form-data")
    return int(re.search(r"/import/(\d+)$", r.headers["Location"]).group(1))


def preview_section(body):
    m = re.search(r'<section id="parsed-preview">(.*?)</section>', body, re.S)
    assert m, "no parsed preview on the page"
    return m.group(1)


def test_preview_shows_parsed_rows_without_importing(post, client, category, txs, app):
    groceries = category("Groceries")
    post("/rules", {"pattern": "tesco", "category_id": str(groceries)})
    iid = upload(post, BANK_CSV)
    r = post(f"/import/{iid}", dict(MAPPING, action="preview", remember="1"))
    assert r.status_code == 200
    section = preview_section(r.get_data(as_text=True))
    assert "add <strong>3</strong> transactions" in section
    assert "skip 0 duplicates" in section and "1 row with errors" in section
    assert "<td>2026-10-01</td><td>TESCO STORES 1234</td>" in section
    assert "-23.45" in section and "+2,500.00" in section
    assert "<td>Groceries</td>" in section
    assert "Coffee &lt;Bar&gt;" in section  # escaped
    assert "line 5:" in section
    # nothing stored, the upload is still pending and no mapping was saved
    assert txs() == []
    assert client.get(f"/import/{iid}").status_code == 200
    with app.app_context():
        assert db.list_import_profiles() == []


def test_preview_keeps_the_chosen_mapping_in_the_form(post):
    iid = upload(post, BANK_CSV)
    form = dict(MAPPING, action="preview", negate="1", note_col="")
    body = post(f"/import/{iid}", form).get_data(as_text=True)
    assert re.search(r'name="negate" value="1" checked', body)
    assert re.search(r'name="note_col">\s*<option value="">\(none\)</option>\s*<option value="0" >', body)
    # flipped signs show in the preview
    assert "+23.45" in preview_section(body)


def test_preview_marks_duplicates(post):
    iid = upload(post, BANK_CSV)
    post(f"/import/{iid}", MAPPING)
    iid2 = upload(post, BANK_CSV)
    section = preview_section(post(f"/import/{iid2}", dict(MAPPING, action="preview"))
                              .get_data(as_text=True))
    assert "add <strong>0</strong> transactions" in section
    assert "skip 3 duplicates" in section
    assert section.count("duplicate, skipped") == 3
    # importing duplicates anyway turns them back into new rows
    section = preview_section(post(f"/import/{iid2}", dict(
        MAPPING, action="preview", allow_duplicates="1")).get_data(as_text=True))
    assert "add <strong>3</strong> transactions" in section
    assert "duplicate, skipped" not in section


def test_preview_lists_only_the_first_rows(post):
    lines = ["Date,Description,Amount"] + [
        f"2026-10-{d:02d},Shop {d},-1.00" for d in range(1, 26)]
    iid = upload(post, "\n".join(lines) + "\n")
    form = {"date_col": "0", "date_fmt": "%Y-%m-%d", "mode": "single",
            "amount_col": "2", "payee_col": "1", "action": "preview"}
    section = preview_section(post(f"/import/{iid}", form).get_data(as_text=True))
    assert "First 10 of 25 parsed rows" in section
    assert "Shop 10<" in section and "Shop 11<" not in section


def test_preview_with_bad_mapping_shows_errors(post):
    iid = upload(post, BANK_CSV)
    r = post(f"/import/{iid}", dict(MAPPING, action="preview", date_fmt="%d/%m/%Y"))
    assert r.status_code == 400
    body = r.get_data(as_text=True)
    assert "No row could be imported with this mapping." in body
    assert "parsed-preview" not in body


def test_import_after_preview_commits(post, txs):
    iid = upload(post, BANK_CSV)
    post(f"/import/{iid}", dict(MAPPING, action="preview"))
    r = post(f"/import/{iid}", dict(MAPPING, action="import"))
    assert "imported 3 transactions" in r.get_data(as_text=True)
    assert len(txs()) == 3


def test_preview_requires_csrf(post, client, txs):
    iid = upload(post, BANK_CSV)
    r = client.post(f"/import/{iid}", data=dict(MAPPING, action="preview"))
    assert r.status_code == 400
    assert txs() == []
