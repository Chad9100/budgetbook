"""Rule-based auto-categorisation: "payee contains X -> category Y"."""
from . import db


def normalise_payee(payee):
    """Collapse whitespace and casefold, for matching and duplicate checks."""
    return " ".join(str(payee).split()).casefold()


def pick_category(payee, rules):
    """Return the category id of the best matching rule, or None.

    ``rules`` is a sequence of (pattern, category_id) in creation order.
    Matching is a case-insensitive substring test. When several rules match,
    the longest pattern wins (it is the most specific); ties go to the rule
    created first.
    """
    text = normalise_payee(payee)
    best_len, best_cat = 0, None
    for pattern, category_id in rules:
        pat = normalise_payee(pattern)
        if pat and pat in text and len(pat) > best_len:
            best_len, best_cat = len(pat), category_id
    return best_cat


def load_rules():
    return [(r["pattern"], r["category_id"]) for r in db.list_rules()]


def apply_to_uncategorised():
    """Categorise every uncategorised transaction a rule matches.
    Returns how many were changed."""
    rules = load_rules()
    if not rules:
        return 0
    pairs = []
    for row in db.uncategorised_transactions():
        cat = pick_category(row["payee"], rules)
        if cat is not None:
            pairs.append((cat, row["id"]))
    if pairs:
        db.set_categories(pairs)
    return len(pairs)
