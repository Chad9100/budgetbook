import re

import pytest

from budgetbook import create_app


@pytest.fixture
def app(tmp_path):
    return create_app({"TESTING": True, "SECRET_KEY": "test",
                       "DATABASE": str(tmp_path / "test.db")})


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def token(client):
    """The session's CSRF token, read from a rendered form."""
    html = client.get("/transactions/new").get_data(as_text=True)
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


@pytest.fixture
def post(client, token):
    """POST a form with the CSRF token filled in."""
    def _post(url, data=None, **kw):
        data = dict(data or {})
        data.setdefault("csrf_token", token)
        return client.post(url, data=data, **kw)
    return _post


@pytest.fixture
def category(post, app):
    """Create a category by name and return its id."""
    def _category(name):
        assert post("/categories", {"name": name}).status_code == 302
        with app.app_context():
            from budgetbook import db
            return next(c["id"] for c in db.list_categories() if c["name"] == name)
    return _category


@pytest.fixture
def add_tx(post):
    def _add(**kw):
        data = {"date": "2026-10-05", "kind": "expense", "amount": "10.00",
                "payee": "Shop", "category_id": "", "note": ""}
        data.update({k: str(v) for k, v in kw.items()})
        return post("/transactions/new", data)
    return _add


@pytest.fixture
def txs(app):
    """All stored transactions as dicts, oldest first."""
    def _txs():
        with app.app_context():
            from budgetbook import db
            return [dict(r) for r in reversed(db.list_transactions())]
    return _txs
