import re

import pytest

from budgetbook import create_app


@pytest.fixture
def small(tmp_path):
    app = create_app({"TESTING": True, "SECRET_KEY": "test", "PAGE_SIZE": 3,
                      "DATABASE": str(tmp_path / "p.db")})
    return app.test_client()


def seed(client, n):
    html = client.get("/transactions/new").get_data(as_text=True)
    tok = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
    for i in range(1, n + 1):
        client.post("/transactions/new", data={
            "csrf_token": tok, "date": "2026-10-%02d" % i, "kind": "expense",
            "amount": "10.00", "payee": "Shop%02d" % i})


def page(client, url):
    return client.get(url).get_data(as_text=True)


def test_single_page_has_no_pager(small):
    seed(small, 3)
    assert "pager" not in page(small, "/")


def test_pages_split_newest_first(small):
    seed(small, 7)
    p1 = page(small, "/")
    assert "Shop07" in p1 and "Shop05" in p1 and "Shop04" not in p1
    assert "Showing 1&ndash;3 of 7 (page 1 of 3)" in p1
    p3 = page(small, "/?page=3")
    assert "Shop01" in p3 and "Shop02" not in p3
    assert "Showing 7&ndash;7 of 7" in p3 and "Older" not in p3


def test_totals_cover_all_pages(small):
    seed(small, 7)
    assert "7 transactions" in page(small, "/")
    assert "70.00" in page(small, "/?page=2")


def test_bad_page_is_clamped(small):
    seed(small, 7)
    assert "page 3 of 3" in page(small, "/?page=99")
    assert "page 1 of 3" in page(small, "/?page=abc")
    assert "page 1 of 3" in page(small, "/?page=0")


def test_filters_kept_in_links(small):
    seed(small, 7)
    html = page(small, "/?q=Shop&page=2")
    assert "q=Shop" in html and "page=3" in html and "page=1" in html
