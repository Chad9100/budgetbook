"""Rule-based auto-categorisation: "payee <matches> X -> category Y"."""
import re

from . import db

# Stored value -> wording shown in the UI ("payee contains X").
MATCH_TYPES = {
    "contains": "contains",
    "starts": "starts with",
    "exact": "is exactly",
    "regex": "matches regex",
}


def normalise_payee(payee):
    """Collapse whitespace and casefold, for matching and duplicate checks."""
    return " ".join(str(payee).split()).casefold()


def compile_regex(pattern):
    """Compile a rule's regular expression (case-insensitive).
    Raises ``re.error`` when the pattern is invalid."""
    return re.compile(pattern, re.IGNORECASE)


def in_amount_range(amount_cents, min_cents, max_cents):
    """True when the size of the amount (ignoring its sign) is within the
    optional inclusive bounds. Unknown amounts only match unbounded rules."""
    if min_cents is None and max_cents is None:
        return True
    if amount_cents is None:
        return False
    size = abs(amount_cents)
    return ((min_cents is None or size >= min_cents)
            and (max_cents is None or size <= max_cents))


def _rank(text, spaced, pattern, match_type):
    """Return a sort key for a matching rule (bigger is more specific), or
    None when the rule does not match."""
    if match_type == "regex":
        try:
            found = compile_regex(pattern).search(spaced)
        except re.error:
            return None
        return (1, 0) if found else None
    pat = normalise_payee(pattern)
    if not pat:
        return None
    if match_type == "exact":
        return (3, len(pat)) if text == pat else None
    if match_type == "starts":
        return (2, len(pat)) if text.startswith(pat) else None
    return (2, len(pat)) if pat in text else None


def pick_category(payee, rules, amount_cents=None):
    """Return the category id of the best matching rule, or None.

    ``rules`` is a sequence of (pattern, category_id[, match_type[, min_cents,
    max_cents]]) in creation order; the match type defaults to "contains".
    Text matches are case-insensitive and ignore extra spaces. A rule with an
    amount range only matches a transaction whose size (sign ignored) is in
    it. When several rules match, an "is exactly" rule wins, then the longest
    "contains"/"starts with" pattern, then a regex rule; at equal rank a rule
    with an amount range beats one without, then the rule created first wins.
    """
    spaced = " ".join(str(payee).split())
    text = spaced.casefold()
    best_key, best_cat = None, None
    for rule in rules:
        pattern, category_id = rule[0], rule[1]
        match_type = rule[2] if len(rule) > 2 else "contains"
        lo = rule[3] if len(rule) > 3 else None
        hi = rule[4] if len(rule) > 4 else None
        if not in_amount_range(amount_cents, lo, hi):
            continue
        key = _rank(text, spaced, pattern, match_type)
        if key is not None:
            key += (lo is not None or hi is not None,)
        if key is not None and (best_key is None or key > best_key):
            best_key, best_cat = key, category_id
    return best_cat


def load_rules():
    return [(r["pattern"], r["category_id"], r["match_type"],
             r["min_cents"], r["max_cents"]) for r in db.list_rules()]


def apply_to_uncategorised():
    """Categorise every uncategorised transaction a rule matches.
    Returns how many were changed."""
    rules = load_rules()
    if not rules:
        return 0
    pairs = []
    for row in db.uncategorised_transactions():
        cat = pick_category(row["payee"], rules, row["amount_cents"])
        if cat is not None:
            pairs.append((cat, row["id"]))
    if pairs:
        db.set_categories(pairs)
    return len(pairs)
