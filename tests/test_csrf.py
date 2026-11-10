def test_post_without_token_is_rejected(client, txs):
    client.get("/")
    r = client.post("/transactions/new", data={
        "date": "2026-10-01", "kind": "expense", "amount": "1", "payee": "x"})
    assert r.status_code == 400
    assert txs() == []


def test_post_with_wrong_token_is_rejected(client, token):
    r = client.post("/categories", data={"name": "Food", "csrf_token": token + "x"})
    assert r.status_code == 400


def test_token_from_another_session_is_rejected(app, token):
    other = app.test_client()
    other.get("/")
    r = other.post("/categories", data={"name": "Food", "csrf_token": token})
    assert r.status_code == 400


def test_every_form_carries_the_token(client, post, add_tx, category):
    category("Food")
    add_tx()
    for url in ["/", "/transactions/new", "/categories", "/rules", "/budgets", "/import"]:
        body = client.get(url).get_data(as_text=True)
        assert body.count("<form method=\"post\"") == body.count('name="csrf_token"'), url


def test_session_cookie_is_samesite_lax(client):
    r = client.get("/")
    cookie = r.headers.get("Set-Cookie", "")
    assert "SameSite=Lax" in cookie and "HttpOnly" in cookie
