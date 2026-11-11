import re

import pytest

from budgetbook import create_app, db


@pytest.fixture
def seeded(app, client, post, category):
    food = category("Bulk Food")
    for i in range(1, 5):
        post("/transactions/new", {"date": "2026-10-%02d" % i, "kind": "expense",
                                   "amount": "5.00", "payee": "Shop%d" % i})
    with app.app_context():
        ids = [r["id"] for r in db.list_transactions(None, "", "", "")]
    return food, sorted(ids)


def cats(app):
    with app.app_context():
        return {r["payee"]: r["category"] for r in db.list_transactions(None, "", "", "")}


def test_list_has_checkboxes_and_bulk_form(client, seeded):
    html = client.get("/").get_data(as_text=True)
    assert html.count('name="ids"') == 4
    assert 'action="/transactions/bulk"' in html


def test_set_category_for_selected_only(app, post, seeded):
    food, ids = seeded
    r = post("/transactions/bulk", {"ids": [str(ids[0]), str(ids[1])],
                                    "action": "category", "category": str(food)})
    assert r.status_code == 302
    got = cats(app)
    assert sorted(k for k, v in got.items() if v == "Bulk Food") == ["Shop1", "Shop2"]
    assert got["Shop3"] is None


def test_clear_category(app, post, seeded):
    food, ids = seeded
    post("/transactions/bulk", {"ids": [str(i) for i in ids], "action": "category",
                                "category": str(food)})
    post("/transactions/bulk", {"ids": [str(ids[0])], "action": "category",
                                "category": "none"})
    assert list(cats(app).values()).count("Bulk Food") == 3


def test_delete_selected(app, client, post, seeded):
    _, ids = seeded
    r = post("/transactions/bulk", {"ids": [str(ids[0]), str(ids[2]), "9999"],
                                    "action": "delete"}, follow_redirects=True)
    assert "Deleted 2 transactions." in r.get_data(as_text=True)
    assert len(cats(app)) == 2


def test_nothing_selected_changes_nothing(app, post, seeded):
    r = post("/transactions/bulk", {"action": "delete"}, follow_redirects=True)
    assert "Select at least one" in r.get_data(as_text=True)
    assert len(cats(app)) == 4


def test_bad_category_or_action_changes_nothing(app, post, seeded):
    _, ids = seeded
    post("/transactions/bulk", {"ids": [str(ids[0])], "action": "category",
                                "category": "9999"})
    post("/transactions/bulk", {"ids": [str(ids[0])], "action": "bogus"})
    post("/transactions/bulk", {"ids": ["abc"], "action": "delete"})
    assert len(cats(app)) == 4 and set(cats(app).values()) == {None}


def test_redirect_back_keeps_filters_and_is_local(post, seeded):
    _, ids = seeded
    r = post("/transactions/bulk", {"ids": [str(ids[0])], "action": "category",
                                    "category": "none", "back": "/?q=Shop&page=1"})
    assert r.headers["Location"].endswith("/?q=Shop&page=1")
    for evil in ("http://evil.example/", "//evil.example/", "/\\evil"):
        r = post("/transactions/bulk", {"ids": [str(ids[0])], "action": "category",
                                        "category": "none", "back": evil})
        assert "evil" not in r.headers["Location"]


def test_requires_csrf(client, seeded):
    _, ids = seeded
    assert client.post("/transactions/bulk",
                       data={"ids": [str(ids[0])], "action": "delete"}).status_code == 400


def test_back_field_rendered_with_filters(client, seeded):
    html = client.get("/?q=Shop").get_data(as_text=True)
    assert re.search(r'name="back" value="/\?q=Shop"', html)
