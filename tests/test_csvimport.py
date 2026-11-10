from collections import Counter

import pytest

from budgetbook.csvimport import (Mapping, decode, detect_date_format,
                                  dup_key, guess_mapping, mapping_from_form,
                                  parse_rows, read_rows, split_duplicates)


def test_decode_strips_bom_and_falls_back_to_cp1252():
    assert decode("﻿Date,Amount".encode("utf-8")) == "Date,Amount"
    assert decode("Café".encode("cp1252")) == "Café"


def test_read_rows_sniffs_semicolons_and_skips_blank_lines():
    text = "Date;Amount;Payee\n\n01.10.2026;-1,50;Bakery\n02.10.2026;20,00;Refund\n"
    header, rows = read_rows(text)
    assert header == ["Date", "Amount", "Payee"]
    assert [cells for _, cells in rows] == [["01.10.2026", "-1,50", "Bakery"],
                                            ["02.10.2026", "20,00", "Refund"]]
    assert rows[0][0] == 3  # real line number in the file


def test_read_rows_empty_file():
    with pytest.raises(ValueError):
        read_rows("\n\n")


def test_detect_date_format():
    assert detect_date_format(["2026-10-01", "2026-10-31"]) == "%Y-%m-%d"
    assert detect_date_format(["01/10/2026", "31/10/2026"]) == "%d/%m/%Y"
    assert detect_date_format(["10/31/2026", "10/01/2026"]) == "%m/%d/%Y"
    assert detect_date_format(["yesterday"]) == ""


def test_guess_mapping_single_amount():
    header = ["Transaction Date", "Description", "Amount", "Memo"]
    g = guess_mapping(header, [(2, ["2026-10-01", "Shop", "-1.00", "x"])])
    assert (g["date"], g["payee"], g["amount"], g["note"]) == (0, 1, 2, 3)
    assert g["date_fmt"] == "%Y-%m-%d"
    assert g["mode"] == "single"


def test_guess_mapping_split_columns():
    g = guess_mapping(["Date", "Details", "Money Out", "Money In"], [])
    assert g["mode"] == "split"
    assert (g["debit"], g["credit"], g["payee"]) == (2, 3, 1)


def test_mapping_from_form_reports_missing_columns():
    _, errors = mapping_from_form({"mode": "single", "date_fmt": "%Y-%m-%d"}, 3)
    assert any("date column" in e for e in errors)
    assert any("amount column" in e for e in errors)
    _, errors = mapping_from_form({"date_col": "9", "payee_col": "0", "amount_col": "1",
                                   "date_fmt": "%Y-%m-%d"}, 3)
    assert errors == ["The date column is not in the file."]
    _, errors = mapping_from_form({"date_col": "0", "payee_col": "1", "amount_col": "2",
                                   "date_fmt": "%s"}, 3)
    assert errors == ["Choose a date format."]


def test_parse_rows_single_column_with_errors():
    rows = [(2, ["2026-10-01", "Bakery", "-3.50"]),
            (3, ["2026-13-01", "Bad date", "-1"]),
            (4, ["2026-10-02", "Zero", "0"]),
            (5, ["2026-10-03", "", "-1"]),
            (6, ["2026-10-04", "Short"])]
    m = Mapping(date_col=0, date_fmt="%Y-%m-%d", payee_col=1, amount_col=2)
    parsed, errors = parse_rows(rows, m)
    assert parsed == [{"line": 2, "date": "2026-10-01", "amount_cents": -350,
                       "payee": "Bakery", "note": ""}]
    assert [e.split(":")[0] for e in errors] == ["line 3", "line 4", "line 5", "line 6"]
    assert "zero" in errors[1] and "payee" in errors[2] and "columns" in errors[3]


def test_parse_rows_split_columns_negate_and_decimal_comma():
    rows = [(2, ["01.10.2026", "Rent", "1.200,00", ""]),
            (3, ["02.10.2026", "Salary", "", "2.500,50"])]
    m = Mapping(date_col=0, date_fmt="%d.%m.%Y", payee_col=1, debit_col=2,
                credit_col=3, decimal_comma=True)
    parsed, errors = parse_rows(rows, m)
    assert errors == []
    assert [t["amount_cents"] for t in parsed] == [-120000, 250050]
    m.negate = True
    parsed, _ = parse_rows(rows, m)
    assert [t["amount_cents"] for t in parsed] == [120000, -250050]


def test_split_duplicates_counts_occurrences():
    parsed = [{"date": "2026-10-01", "amount_cents": -500, "payee": "Coffee  Shop"},
              {"date": "2026-10-01", "amount_cents": -500, "payee": "coffee shop"},
              {"date": "2026-10-02", "amount_cents": -500, "payee": "Coffee Shop"}]
    existing = Counter({dup_key("2026-10-01", -500, "COFFEE SHOP"): 1})
    new, dupes = split_duplicates(parsed, existing)
    # one stored copy covers only the first of the two identical rows
    assert dupes == [parsed[0]]
    assert new == parsed[1:]
