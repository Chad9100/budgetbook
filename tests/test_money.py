import pytest

from budgetbook.money import (cents_to_input, format_cents, month_label,
                              month_range, parse_amount, shift_month,
                              valid_month)


@pytest.mark.parametrize("text, cents", [
    ("12", 1200),
    ("12.5", 1250),
    ("12.34", 1234),
    ("-12.34", -1234),
    ("+3", 300),
    (".5", 50),
    ("1,234.56", 123456),
    ("$1,000", 100000),
    ("€ 9.99", 999),
    ("(45.00)", -4500),
    ("45.00-", -4500),
    ("−12.00", -1200),
    ("0.01", 1),
])
def test_parse_amount_valid(text, cents):
    assert parse_amount(text) == cents


@pytest.mark.parametrize("text, cents", [
    ("1.234,56", 123456),
    ("12,5", 1250),
    ("-0,99", -99),
])
def test_parse_amount_decimal_comma(text, cents):
    assert parse_amount(text, decimal_comma=True) == cents


@pytest.mark.parametrize("text", ["", "   ", "abc", "1.234", "12,50", "1,23,4", "1.2.3", "--5", "12e3", "nan"])
def test_parse_amount_rejects(text):
    with pytest.raises(ValueError):
        parse_amount(text)


def test_parse_amount_rejects_absurdly_large():
    with pytest.raises(ValueError, match="too large"):
        parse_amount("999999999999999")


def test_format_cents():
    assert format_cents(0) == "0.00"
    assert format_cents(5) == "0.05"
    assert format_cents(123456789) == "1,234,567.89"
    assert format_cents(-1050) == "-10.50"
    assert format_cents(1050, signed=True) == "+10.50"
    assert cents_to_input(-123405) == "1234.05"


def test_month_helpers():
    assert valid_month("2026-11")
    assert not valid_month("2026-13")
    assert not valid_month("26-11")
    assert not valid_month("")
    assert shift_month("2026-01", -1) == "2025-12"
    assert shift_month("2026-12", 1) == "2027-01"
    assert shift_month("2026-05", -17) == "2024-12"
    assert month_range("2026-12") == ("2026-12-01", "2027-01-01")
    assert month_label("2026-02") == "February 2026"
