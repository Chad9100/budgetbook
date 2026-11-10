"""Validation of submitted forms. Each validator returns (clean, errors)."""
import re
from datetime import datetime

from .money import parse_amount
from .rules import MATCH_TYPES, compile_regex

MAX_PAYEE = 200
MAX_NOTE = 1000
MAX_NAME = 60
MAX_PATTERN = 100


def clean_text(value):
    return " ".join((value or "").split())


def parse_iso_date(text):
    """Strict ``YYYY-MM-DD``; returns the normalised string or raises ValueError."""
    return datetime.strptime((text or "").strip(), "%Y-%m-%d").date().isoformat()


def validate_account(form):
    """Validate the new-account form: name, kind and opening balance."""
    from .db import ACCOUNT_KINDS
    name, errors = validate_name(form)
    kind = (form.get("kind") or "current").strip()
    if kind not in ACCOUNT_KINDS:
        errors.append("Unknown account type.")
    opening = 0
    text = (form.get("opening") or "").strip()
    if text:
        try:
            opening = parse_amount(text)
        except ValueError as e:
            errors.append(f"Opening balance: {e}.")
    return {"name": name, "kind": kind, "opening_cents": opening}, errors


def parse_account(value, account_ids):
    """Return (account_id or None, error or None); blank means no account."""
    value = (value or "").strip()
    if not value:
        return None, None
    if not value.isdigit() or int(value) not in account_ids:
        return None, "Unknown account."
    return int(value), None


def validate_transaction(form, category_ids, account_ids=()):
    errors, clean = [], {}
    clean["account_id"], err = parse_account(form.get("account_id"), account_ids)
    if err:
        errors.append(err)
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
    match_type = (form.get("match_type") or "contains").strip()
    if match_type not in MATCH_TYPES:
        errors.append("Unknown match type.")
        match_type = "contains"
    pattern = clean_text(form.get("pattern"))
    if not pattern:
        errors.append("Pattern is required.")
    elif len(pattern) > MAX_PATTERN:
        errors.append(f"Pattern must be at most {MAX_PATTERN} characters.")
    elif match_type == "regex":
        try:
            compile_regex(pattern)
        except re.error as e:
            errors.append(f"Invalid regular expression: {e}.")
    cat, err = parse_category(form.get("category_id"), category_ids, required=True)
    if err:
        errors.append(err)
    bounds = {}
    for key, label in (("min", "Minimum"), ("max", "Maximum")):
        text = (form.get(f"{key}_amount") or "").strip()
        bounds[key] = None
        if not text:
            continue
        try:
            value = parse_amount(text)
            if value < 0:
                raise ValueError("must not be negative")
            bounds[key] = value
        except ValueError as e:
            errors.append(f"{label} amount: {e}.")
    if (bounds["min"] is not None and bounds["max"] is not None
            and bounds["min"] > bounds["max"]):
        errors.append("Minimum amount must not be greater than the maximum.")
    return {"pattern": pattern, "category_id": cat, "match_type": match_type,
            "min_cents": bounds["min"], "max_cents": bounds["max"]}, errors
