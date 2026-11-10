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


def pick_category(payee, rules):
    """Return the category id of the best matching rule, or None.

    ``rules`` is a sequence of (pattern, category_id[, match_type]) in
    creation order; the match type defaults to "contains". Text matches are
    case-insensitive and ignore extra spaces. When several rules match, an
    "is exactly" rule wins, then the longest "contains"/"starts with"
    pattern, then a regex rule; ties go to the rule created first.
    """
    spaced = " ".join(str(payee).split())
    text = spaced.casefold()
    best_key, best_cat = None, None
    for rule in rules:
        pattern, category_id = rule[0], rule[1]
        match_type = rule[2] if len(rule) > 2 else "contains"
        key = _rank(text, spaced, pattern, match_type)
        if key is not None and (best_key is None or key > best_key):
            best_key, best_cat = key, category_id
    return best_cat


def load_rules():
    return [(r["pattern"], r["category_id"], r["match_type"]) for r in db.list_rules()]


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
