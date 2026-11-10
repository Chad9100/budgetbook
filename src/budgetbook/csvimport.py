"""Bank CSV import: decoding, column mapping, row parsing and duplicate detection."""
import csv
import io
from collections import Counter
from dataclasses import dataclass
from datetime import datetime

from .forms import MAX_NOTE, MAX_PAYEE, clean_text
from .money import parse_amount
from .rules import normalise_payee

# (strptime format, label shown in the mapping form)
DATE_FORMATS = [
    ("%Y-%m-%d", "YYYY-MM-DD"),
    ("%Y/%m/%d", "YYYY/MM/DD"),
    ("%d/%m/%Y", "DD/MM/YYYY"),
    ("%m/%d/%Y", "MM/DD/YYYY"),
    ("%d.%m.%Y", "DD.MM.YYYY"),
    ("%d-%m-%Y", "DD-MM-YYYY"),
    ("%m-%d-%Y", "MM-DD-YYYY"),
    ("%Y%m%d", "YYYYMMDD"),
]
_KNOWN_FORMATS = {f for f, _ in DATE_FORMATS}

_GUESSES = {
    "date": ["date", "booking date", "transaction date", "posted", "posting date", "value date"],
    "amount": ["amount", "value", "sum"],
    "debit": ["debit", "withdrawal", "withdrawals", "money out", "paid out", "out"],
    "credit": ["credit", "deposit", "deposits", "money in", "paid in", "in"],
    "payee": ["payee", "description", "merchant", "name", "counterparty", "details", "narrative"],
    "note": ["memo", "note", "notes", "reference"],
}


def decode(raw):
    """Bank exports are usually UTF-8 (often with a BOM) or Windows-1252."""
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def read_rows(text):
    """Return (header, rows) where rows are (line_number, cells).
    Raises ValueError for an empty file."""
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    header, rows = None, []
    for cells in reader:
        cells = [c.strip() for c in cells]
        if not any(cells):
            continue
        if header is None:
            header = cells
        else:
            rows.append((reader.line_num, cells))
    if header is None:
        raise ValueError("the file is empty")
    return header, rows


def _find(header, names, taken=()):
    lowered = [h.casefold() for h in header]
    for name in names:
        for i, h in enumerate(lowered):
            if h == name and i not in taken:
                return i
    for name in names:
        if len(name) < 4:
            continue
        for i, h in enumerate(lowered):
            if name in h and i not in taken:
                return i
    return None


def detect_date_format(values):
    """First known format that parses every non-empty value, else ""."""
    values = [v for v in values if v]
    if not values:
        return ""
    for fmt, _ in DATE_FORMATS:
        try:
            for v in values:
                datetime.strptime(v, fmt)
            return fmt
        except ValueError:
            continue
    return ""


def guess_mapping(header, rows):
    """Best-effort defaults for the mapping form (column indexes or None)."""
    m = {}
    taken = set()
    for field in ("date", "amount", "debit", "credit", "payee", "note"):
        idx = _find(header, _GUESSES[field], taken)
        m[field] = idx
        if idx is not None:
            taken.add(idx)
    if m["date"] is not None:
        m["date_fmt"] = detect_date_format(
            [cells[m["date"]] for _, cells in rows[:200] if len(cells) > m["date"]])
    else:
        m["date_fmt"] = ""
    m["mode"] = "split" if m["amount"] is None and (m["debit"] is not None or m["credit"] is not None) else "single"
    return m


@dataclass
class Mapping:
    date_col: int
    date_fmt: str
    payee_col: int
    amount_col: int | None = None
    debit_col: int | None = None
    credit_col: int | None = None
    note_col: int | None = None
    decimal_comma: bool = False
    negate: bool = False


def mapping_from_form(form, ncols):
    """Build a Mapping from the submitted mapping form. Returns (mapping, errors)."""
    errors = []

    def col(name, label, required):
        value = (form.get(name) or "").strip()
        if value == "":
            if required:
                errors.append(f"Choose the {label} column.")
            return None
        try:
            idx = int(value)
        except ValueError:
            idx = -1
        if not 0 <= idx < ncols:
            errors.append(f"The {label} column is not in the file.")
            return None
        return idx

    date_col = col("date_col", "date", True)
    payee_col = col("payee_col", "payee", True)
    note_col = col("note_col", "note", False)
    mode = form.get("mode", "single")
    amount_col = debit_col = credit_col = None
    if mode == "split":
        debit_col = col("debit_col", "debit", False)
        credit_col = col("credit_col", "credit", False)
        if debit_col is None and credit_col is None and not errors:
            errors.append("Choose a debit column, a credit column, or both.")
    else:
        amount_col = col("amount_col", "amount", True)
    date_fmt = form.get("date_fmt", "")
    if date_fmt not in _KNOWN_FORMATS:
        errors.append("Choose a date format.")
    mapping = Mapping(
        date_col=date_col, date_fmt=date_fmt, payee_col=payee_col,
        amount_col=amount_col, debit_col=debit_col, credit_col=credit_col,
        note_col=note_col, decimal_comma=form.get("decimal") == "comma",
        negate=bool(form.get("negate")))
    return mapping, errors


def _cell(cells, idx):
    if idx is None:
        return ""
    if idx >= len(cells):
        raise ValueError("row has too few columns")
    return cells[idx]


def parse_rows(rows, mapping):
    """Turn raw rows into transactions. Returns (parsed, errors) where each
    parsed item is a dict with line, date, amount_cents, payee, note."""
    parsed, errors = [], []
    for line, cells in rows:
        try:
            raw_date = _cell(cells, mapping.date_col)
            try:
                when = datetime.strptime(raw_date, mapping.date_fmt).date().isoformat()
            except ValueError:
                raise ValueError(f"date {raw_date!r} does not match the chosen format") from None
            if mapping.amount_col is not None:
                cents = parse_amount(_cell(cells, mapping.amount_col), mapping.decimal_comma)
            else:
                debit = _cell(cells, mapping.debit_col)
                credit = _cell(cells, mapping.credit_col)
                if not debit and not credit:
                    raise ValueError("no debit or credit amount")
                cents = 0
                if debit:
                    cents -= abs(parse_amount(debit, mapping.decimal_comma))
                if credit:
                    cents += abs(parse_amount(credit, mapping.decimal_comma))
            if mapping.negate:
                cents = -cents
            if cents == 0:
                raise ValueError("amount is zero")
            payee = clean_text(_cell(cells, mapping.payee_col))[:MAX_PAYEE]
            if not payee:
                raise ValueError("payee is empty")
            note = _cell(cells, mapping.note_col).strip()[:MAX_NOTE]
        except ValueError as e:
            errors.append(f"line {line}: {e}")
            continue
        parsed.append({"line": line, "date": when, "amount_cents": cents,
                       "payee": payee, "note": note})
    return parsed, errors


def dup_key(date, amount_cents, payee):
    return (date, int(amount_cents), normalise_payee(payee))


def split_duplicates(parsed, existing):
    """Split parsed rows into (new, duplicates).

    ``existing`` counts transactions already stored per ``dup_key``. A row is
    a duplicate while the file has not yet used up the stored copies, so
    re-importing an overlapping statement skips what is already there, but two
    genuinely identical purchases on the same day in a new file both import.
    """
    seen = Counter()
    new, dupes = [], []
    for tx in parsed:
        key = dup_key(tx["date"], tx["amount_cents"], tx["payee"])
        seen[key] += 1
        (dupes if seen[key] <= existing.get(key, 0) else new).append(tx)
    return new, dupes
