"""Money and month helpers. Amounts are always integer cents."""
import re
from datetime import date

MAX_CENTS = 10**13  # one hundred billion; anything bigger is a typo

_SYMBOLS = re.compile(r"[$€£¥\s '’]")
_NUMBER = re.compile(r"^(?=\.?\d)\d*(?:\.\d{1,2})?$")
_GROUPED = re.compile(r"^\d{1,3}(?:,\d{3})+$")
_MONTH =re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def parse_amount(text, decimal_comma=False):
    """Parse a human-written amount into signed integer cents.

    Accepts ``12``, ``-12.5``, ``1,234.56``, ``$12.00``, ``(12.00)`` (negative),
    ``12.00-`` (negative) and, with ``decimal_comma=True``, ``1.234,56``.
    Raises ValueError with a readable message on anything else.
    """
    raw = (text or "").strip()
    if not raw:
        raise ValueError("amount is empty")
    s = raw.replace("−", "-")
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1]
    s = _SYMBOLS.sub("", s)
    if s.startswith(("-", "+")):
        negative ^= s[0] == "-"
        s = s[1:]
    elif s.endswith("-"):
        negative, s = not negative, s[:-1]
    s = _SYMBOLS.sub("", s)
    thousands, decimal = (".", ",") if decimal_comma else (",", ".")
    if thousands in s:
        whole_part = s.split(decimal, 1)[0]
        if not _GROUPED.match(whole_part.replace(thousands, ",")):
            raise ValueError(f"not a valid amount: {raw!r}")
        s = s.replace(thousands, "")
    s = s.replace(decimal, ".")
    if not _NUMBER.match(s):
        raise ValueError(f"not a valid amount: {raw!r}")
    whole, _, frac = s.partition(".")
    cents = int(whole or "0") * 100 + int((frac + "00")[:2])
    if cents >= MAX_CENTS:
        raise ValueError(f"amount is too large: {raw!r}")
    return -cents if negative else cents


def format_cents(cents, signed=False):
    """Format cents as ``1,234.56`` (``-1,234.56`` when negative)."""
    sign = "-" if cents < 0 else ("+" if signed and cents > 0 else "")
    whole, frac = divmod(abs(int(cents)), 100)
    return f"{sign}{whole:,}.{frac:02d}"


def amount_range_text(min_cents, max_cents):
    """Describe a rule's amount range, e.g. `` for amounts of 100.00 or more``;
    empty when there is no limit."""
    if min_cents is None and max_cents is None:
        return ""
    if min_cents is None:
        return f" for amounts up to {format_cents(max_cents)}"
    if max_cents is None:
        return f" for amounts of {format_cents(min_cents)} or more"
    return f" for amounts from {format_cents(min_cents)} to {format_cents(max_cents)}"


def cents_to_input(cents):
    """Plain unsigned value for a form field, e.g. ``1234.50``."""
    whole, frac = divmod(abs(int(cents)), 100)
    return f"{whole}.{frac:02d}"


def valid_month(text):
    return bool(text) and bool(_MONTH.match(text))


def current_month(today=None):
    return (today or date.today()).strftime("%Y-%m")


def shift_month(month, n):
    """``shift_month("2026-01", -1) == "2025-12"``."""
    y, m = int(month[:4]), int(month[5:7])
    idx = y * 12 + (m - 1) + n
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def month_range(month):
    """Half-open ISO date range ``[first day, first day of next month)``."""
    return f"{month}-01", f"{shift_month(month, 1)}-01"


def month_label(month):
    names = ["January", "February", "March", "April", "May", "June", "July",
             "August", "September", "October", "November", "December"]
    return f"{names[int(month[5:7]) - 1]} {month[:4]}"
