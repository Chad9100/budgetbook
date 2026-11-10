"""Validation of submitted forms. Each validator returns (clean, errors)."""
from datetime import datetime

from .money import parse_amount

MAX_PAYEE = 200
MAX_NOTE = 1000
MAX_NAME = 60
MAX_PATTERN = 100


def clean_text(value):
    return " ".join((value or "").split())


def parse_iso_date(text):
    """Strict ``YYYY-MM-DD``; returns the normalised string or raises ValueError."""
    return datetime.strptime((text or "").strip(), "%Y-%m-%d").date().isoformat()


def validate_transaction(form, category_ids):
    errors, clean = [], {}
    try:
        clean["date"] = parse_iso_date(form.get("date"))
    except ValueError:
        errors.append("Date must be a valid date (YYYY-MM-DD).")

    kind = form.get("kind", "expense")
    if kind not in ("expense", "income"):
        errors.append("Type must be expense or income.")
    try:
        cents = parse_amount(form.get("amount", ""))
        if cents <= 0:
            errors.append("Amount must be greater than zero; pick expense or income for the direction.")
        clean["amount_cents"] = -cents if kind == "expense" else cents
    except ValueError as e:
        errors.append(f"Amount: {e}.")

    payee = clean_text(form.get("payee"))
    if not payee:
        errors.append("Payee is required.")
    elif len(payee) > MAX_PAYEE:
        errors.append(f"Payee must be at most {MAX_PAYEE} characters.")
    clean["payee"] = payee

    clean["category_id"], err = parse_category(form.get("category_id", ""), category_ids)
    if err:
        errors.append(err)

    note = (form.get("note") or "").strip()
    if len(note) > MAX_NOTE:
        errors.append(f"Note must be at most {MAX_NOTE} characters.")
    clean["note"] = note
    return clean, errors


def parse_category(value, category_ids, required=False):
    """Return (category_id or None, error or None)."""
    value = (value or "").strip()
    if not value:
        return None, ("Pick a category." if required else None)
    try:
        cat = int(value)
    except ValueError:
        return None, "Unknown category."
    if cat not in category_ids:
        return None, "Unknown category."
    return cat, None


def validate_name(form):
    name = clean_text(form.get("name"))
    if not name:
        return name, ["Name is required."]
    if len(name) > MAX_NAME:
        return name, [f"Name must be at most {MAX_NAME} characters."]
    return name, []


def validate_rule(form, category_ids):
    errors = []
    pattern = clean_text(form.get("pattern"))
    if not pattern:
        errors.append("Pattern is required.")
    elif len(pattern) > MAX_PATTERN:
        errors.append(f"Pattern must be at most {MAX_PATTERN} characters.")
    cat, err = parse_category(form.get("category_id"), category_ids, required=True)
    if err:
        errors.append(err)
    return {"pattern": pattern, "category_id": cat}, errors
