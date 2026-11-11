def seed(add_tx):
    add_tx(date="2026-09-03", payee="Septshop")
    add_tx(date="2026-10-05", payee="Octshop")


def test_bare_visit_restores_last_month(client, add_tx):
    seed(add_tx)
    client.get("/?month=2026-09")
    html = client.get("/").get_data(as_text=True)
    assert "Septshop" in html and "Octshop" not in html


def test_new_filter_replaces_old(client, add_tx):
    seed(add_tx)
    client.get("/?month=2026-09")
    client.get("/?month=2026-10")
    html = client.get("/").get_data(as_text=True)
    assert "Octshop" in html and "Septshop" not in html


def test_search_and_month_remembered_together(client, add_tx):
    seed(add_tx)
    client.get("/?q=Septshop")
    html = client.get("/").get_data(as_text=True)
    assert "Septshop" in html and "Octshop" not in html


def test_clear_forgets_filters(client, add_tx):
    seed(add_tx)
    client.get("/?month=2026-09")
    html = client.get("/?clear=1").get_data(as_text=True)
    assert "Septshop" in html and "Octshop" in html
    html = client.get("/").get_data(as_text=True)
    assert "Septshop" in html and "Octshop" in html


def test_empty_filter_submit_clears(client, add_tx):
    seed(add_tx)
    client.get("/?month=2026-09")
    client.get("/?month=&q=&category=&account=")
    html = client.get("/").get_data(as_text=True)
    assert "Septshop" in html and "Octshop" in html


def test_all_link_uses_clear(client):
    html = client.get("/").get_data(as_text=True)
    assert 'href="/?clear=1">All</a>' in html


def test_invalid_remembered_values_ignored(client, add_tx):
    seed(add_tx)
    client.get("/?month=garbage&category=x")
    html = client.get("/").get_data(as_text=True)
    assert "Septshop" in html and "Octshop" in html


def test_filters_are_per_browser(app, add_tx):
    seed(add_tx)
    app.test_client().get("/?month=2026-09")
    html = app.test_client().get("/").get_data(as_text=True)
    assert "Septshop" in html and "Octshop" in html
