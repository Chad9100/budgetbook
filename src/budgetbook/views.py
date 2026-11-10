"""Routes. All state changes are POST forms protected by the CSRF token."""
import csv
import io
import os
from datetime import date

from flask import (Response, abort, flash, redirect, render_template, request,
                   url_for)

from . import db, rules
from .csvimport import (DATE_FORMATS, KNOWN_FORMATS, decode, dup_key, guess_mapping,
                        mapping_from_form, parse_rows, read_rows,
                        split_duplicates)
from .forms import (MAX_NAME, validate_account, validate_name, validate_rule,
                    validate_transaction)
from .money import (amount_range_text, cents_to_input, current_month, parse_amount, shift_month,
                    valid_month)

PREVIEW_ROWS = 5
PARSED_PREVIEW_ROWS = 10
# Mapping-form fields remembered in an import profile.
PROFILE_COLS = ("date_col", "amount_col", "debit_col", "credit_col",
                "payee_col", "note_col")
TREND_MONTHS = 6


def month_arg(default_current=True):
    """The ``month`` query argument if valid, else the current month (or "")."""
    month = request.args.get("month", "")
    if valid_month(month):
        return month
    return current_month() if default_current else ""


def bars(items):
    """[(label, cents)] -> rows with a 0-100 ``pct`` relative to the largest."""
    top = max((c for _, c in items), default=0)
    out = []
    for label, cents in items:
        pct = round(cents * 100 / top, 2) if top > 0 and cents > 0 else 0
        out.append({"label": label, "cents": cents, "pct": pct})
    return out


def csv_safe(value):
    """Stop spreadsheet apps from treating a text cell as a formula."""
    value = str(value)
    return "'" + value if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value


def register(app):

    # ------------------------------------------------------------ transactions

    @app.route("/")
    def index():
        month = month_arg(default_current=False)
        q = request.args.get("q", "").strip()
        category = request.args.get("category", "")
        if category not in ("", "none") and not category.isdigit():
            category = ""
        account = request.args.get("account", "")
        if account not in ("", "none") and not account.isdigit():
            account = ""
        txs = db.list_transactions(month or None, q, category, account)
        income = sum(t["amount_cents"] for t in txs if t["amount_cents"] > 0)
        spent = -sum(t["amount_cents"] for t in txs if t["amount_cents"] < 0)
        return render_template(
            "transactions.html", txs=txs, month=month, q=q, category=category,
            account=account, accounts=db.list_accounts(),
            categories=db.list_categories(), income=income, spent=spent,
            this_month=current_month(),
            prev_month=shift_month(month, -1) if month else "",
            next_month=shift_month(month, 1) if month else "")

    def tx_form(tx, errors=(), status=200):
        return render_template("tx_form.html", tx=tx, errors=list(errors),
                               categories=db.list_categories(),
                               accounts=db.list_accounts()), status

    def category_ids():
        return {c["id"] for c in db.list_categories()}

    def account_ids():
        return {a["id"] for a in db.list_accounts()}

    @app.route("/transactions/new", methods=["GET", "POST"])
    def add_transaction():
        if request.method == "POST":
            clean, errors = validate_transaction(request.form, category_ids(),
                                                 account_ids())
            if errors:
                return tx_form(request.form, errors, 400)
            if clean["category_id"] is None:
                clean["category_id"] = rules.pick_category(clean["payee"], rules.load_rules(),
                                                        clean["amount_cents"])
            db.insert_transaction(clean)
            flash("Transaction added.")
            return redirect(url_for("index", month=clean["date"][:7]))
        return tx_form({"date": date.today().isoformat(), "kind": "expense"})

    @app.route("/transactions/<int:tx_id>/edit", methods=["GET", "POST"])
    def edit_transaction(tx_id):
        tx = db.get_transaction(tx_id)
        if tx is None:
            abort(404)
        if request.method == "POST":
            clean, errors = validate_transaction(request.form, category_ids(),
                                                 account_ids())
            if errors:
                return tx_form({**request.form, "id": tx_id}, errors, 400)
            if clean["category_id"] is None:
                clean["category_id"] = rules.pick_category(clean["payee"], rules.load_rules(),
                                                        clean["amount_cents"])
            db.update_transaction(tx_id, clean)
            flash("Transaction updated.")
            return redirect(url_for("index", month=clean["date"][:7]))
        values = dict(tx)
        values["kind"] = "income" if tx["amount_cents"] > 0 else "expense"
        values["amount"] = cents_to_input(tx["amount_cents"])
        values["category_id"] = "" if tx["category_id"] is None else str(tx["category_id"])
        values["account_id"] = "" if tx["account_id"] is None else str(tx["account_id"])
        return tx_form(values)

    # ---------------------------------------------------------------- accounts

    def accounts_page(errors=(), status=200):
        return render_template("accounts.html", accounts=db.list_accounts(),
                               kinds=db.ACCOUNT_KINDS, errors=list(errors)), status

    @app.route("/accounts", methods=["GET", "POST"])
    def accounts():
        if request.method == "POST":
            clean, errors = validate_account(request.form)
            if not errors:
                try:
                    db.add_account(clean["name"], clean["kind"], clean["opening_cents"])
                except ValueError as e:
                    errors = [str(e).capitalize() + "."]
            if errors:
                return accounts_page(errors, 400)
            flash(f"Account {clean['name']!r} added.")
            return redirect(url_for("accounts"))
        return accounts_page()

    @app.post("/accounts/<int:account_id>/delete")
    def delete_account(account_id):
        if not db.delete_account(account_id):
            abort(404)
        flash("Account deleted; its transactions are kept with no account.")
        return redirect(url_for("accounts"))

    @app.post("/transactions/<int:tx_id>/delete")
    def delete_transaction(tx_id):
        tx = db.get_transaction(tx_id)
        if tx is None or not db.delete_transaction(tx_id):
            abort(404)
        flash("Transaction deleted.")
        return redirect(url_for("index", month=tx["date"][:7]))

    @app.route("/export.csv")
    def export_csv():
        month = month_arg(default_current=False)
        out = io.StringIO()
        w = csv.writer(out, lineterminator="\n")
        w.writerow(["date", "amount", "payee", "category", "note"])
        for t in reversed(db.list_transactions(month or None)):
            sign = "-" if t["amount_cents"] < 0 else ""
            w.writerow([t["date"], sign + cents_to_input(t["amount_cents"]),
                        csv_safe(t["payee"]), csv_safe(t["category"] or ""),
                        csv_safe(t["note"])])
        name = f"budgetbook-{month}.csv" if month else "budgetbook.csv"
        return Response(out.getvalue(), mimetype="text/csv", headers={
            "Content-Disposition": f"attachment; filename={name}"})

    # -------------------------------------------------------------- categories

    @app.route("/categories", methods=["GET", "POST"])
    def categories():
        errors, status = [], 200
        if request.method == "POST":
            name, errors = validate_name(request.form)
            if not errors:
                try:
                    db.add_category(name)
                except ValueError as e:
                    errors = [str(e).capitalize() + "."]
            if not errors:
                flash(f"Category {name!r} added.")
                return redirect(url_for("categories"))
            status = 400
        usage = db.category_usage()
        return render_template("categories.html", categories=db.list_categories(),
                               usage=usage, errors=errors), status

    @app.post("/categories/<int:cat_id>/rename")
    def rename_category(cat_id):
        if db.get_category(cat_id) is None:
            abort(404)
        name, errors = validate_name(request.form)
        if not errors:
            try:
                db.rename_category(cat_id, name)
            except ValueError as e:
                errors = [str(e).capitalize() + "."]
        if errors:
            return render_template("categories.html", categories=db.list_categories(),
                                   usage=db.category_usage(), errors=errors), 400
        flash("Category renamed.")
        return redirect(url_for("categories"))

    @app.post("/categories/<int:cat_id>/delete")
    def delete_category(cat_id):
        if not db.delete_category(cat_id):
            abort(404)
        flash("Category deleted; its transactions are now uncategorised.")
        return redirect(url_for("categories"))

    # ------------------------------------------------------------------- rules

    @app.route("/rules", methods=["GET", "POST"])
    def rules_page():
        errors, status, form = [], 200, {}
        if request.method == "POST":
            clean, errors = validate_rule(request.form, category_ids())
            if not errors:
                db.add_rule(clean["pattern"], clean["category_id"],
                            clean["match_type"], clean["min_cents"], clean["max_cents"])
                flash(f"Rule added: payee {rules.MATCH_TYPES[clean['match_type']]}"
                      f" {clean['pattern']!r}"
                      f"{amount_range_text(clean['min_cents'], clean['max_cents'])}.")
                return redirect(url_for("rules_page"))
            status, form = 400, request.form
        elif request.args.get("from_tx", type=int) is not None:
            # "Create rule from this transaction": prefill the form.
            tx = db.get_transaction(request.args.get("from_tx", type=int))
            if tx is None:
                abort(404)
            form = {"match_type": "contains", "pattern": " ".join(tx["payee"].split()),
                    "min_amount": "", "max_amount": "",
                    "category_id": str(tx["category_id"] or "")}
        return render_template("rules.html", rules=db.list_rules(),
                               match_types=rules.MATCH_TYPES,
                               categories=db.list_categories(), errors=errors,
                               form=form,
                               uncategorised=len(db.uncategorised_transactions())), status

    @app.post("/rules/<int:rule_id>/delete")
    def delete_rule(rule_id):
        if not db.delete_rule(rule_id):
            abort(404)
        flash("Rule deleted.")
        return redirect(url_for("rules_page"))

    @app.post("/rules/apply")
    def apply_rules():
        n = rules.apply_to_uncategorised()
        flash(f"Categorised {n} transaction{'s' if n != 1 else ''}.")
        return redirect(url_for("rules_page"))

    @app.route("/rules/reapply", methods=["GET", "POST"])
    def reapply_rules():
        """Preview, then apply, rule changes to already categorised
        transactions. Only the ticked rows are changed, and each is
        re-checked against the current rules at that moment."""
        names = {c["id"]: c["name"] for c in db.list_categories()}
        changes = rules.recategorise_preview()
        if request.method == "POST":
            chosen = set(request.form.getlist("tx_id"))
            pairs = [(cat, row["id"]) for row, cat in changes
                     if str(row["id"]) in chosen]
            if pairs:
                db.set_categories(pairs)
            n = len(pairs)
            flash(f"Recategorised {n} transaction{'s' if n != 1 else ''}.")
            return redirect(url_for("rules_page"))
        rows = [{"tx": row, "new": names[cat]} for row, cat in changes]
        return render_template("rules_reapply.html", rows=rows)

    # ----------------------------------------------------------------- budgets

    def budget_rows(month):
        budgets = db.budgets_for_month(month)
        net = {r["category_id"]: r["net_cents"] for r in db.category_net(month)}
        rows = []
        for c in db.list_categories():
            amount, set_in = budgets.get(c["id"], (None, None))
            spent = -net.get(c["id"], 0)
            row = {"id": c["id"], "name": c["name"], "budget": amount,
                   "set_in": set_in, "spent": spent,
                   "remaining": None if amount is None else amount - spent,
                   "pct": 0}
            if amount:
                row["pct"] = max(0, min(100, round(spent * 100 / amount, 1)))
            elif amount == 0 and spent > 0:
                row["pct"] = 100
            rows.append(row)
        return rows, -net.get(None, 0)

    @app.route("/budgets", methods=["GET", "POST"])
    def budgets():
        month = month_arg()
        errors, status = [], 200
        if request.method == "POST":
            month = request.form.get("month", "")
            if not valid_month(month):
                abort(400, description="Invalid month.")
            updates = []
            for c in db.list_categories():
                raw = request.form.get(f"budget_{c['id']}")
                if raw is None:
                    continue
                raw = raw.strip()
                if raw == "":
                    updates.append((c["id"], None))
                    continue
                try:
                    cents = parse_amount(raw)
                except ValueError as e:
                    errors.append(f"{c['name']}: {e}.")
                    continue
                if cents < 0:
                    errors.append(f"{c['name']}: a budget cannot be negative.")
                    continue
                updates.append((c["id"], cents))
            if not errors:
                for cat_id, cents in updates:
                    db.set_budget(cat_id, month, cents)
                flash("Budgets saved.")
                return redirect(url_for("budgets", month=month))
            status = 400
        rows, uncategorised = budget_rows(month)
        budgeted = [r for r in rows if r["budget"] is not None]
        totals = {"budget": sum(r["budget"] for r in budgeted),
                  "spent": sum(r["spent"] for r in budgeted)}
        totals["remaining"] = totals["budget"] - totals["spent"]
        return render_template("budgets.html", month=month, rows=rows,
                               uncategorised=uncategorised, totals=totals,
                               errors=errors, form=request.form if errors else None,
                               prev_month=shift_month(month, -1),
                               next_month=shift_month(month, 1)), status

    # ------------------------------------------------------------------ report

    @app.route("/report")
    def report():
        month = month_arg()
        income, expenses = db.month_totals(month)
        net_rows = db.category_net(month)
        budgets_map = db.budgets_for_month(month)
        spending = sorted(((r["category"] or "Uncategorised", -r["net_cents"], r["category_id"])
                           for r in net_rows if r["net_cents"] < 0),
                          key=lambda x: -x[1])
        spending_bars = bars([(name, cents) for name, cents, _ in spending])
        for bar, (_, _, cat_id) in zip(spending_bars, spending):
            bar["budget"] = budgets_map.get(cat_id, (None,))[0] if cat_id else None
        income_bars = bars(sorted(((r["category"] or "Uncategorised", r["net_cents"])
                                   for r in net_rows if r["net_cents"] > 0),
                                  key=lambda x: -x[1]))
        trend = []
        for i in range(TREND_MONTHS - 1, -1, -1):
            m = shift_month(month, -i)
            inc, exp = db.month_totals(m)
            trend.append({"month": m, "income": inc, "expenses": exp})
        top = max([t["income"] for t in trend] + [t["expenses"] for t in trend] + [0])
        for t in trend:
            t["income_pct"] = round(t["income"] * 100 / top, 2) if top else 0
            t["expenses_pct"] = round(t["expenses"] * 100 / top, 2) if top else 0
        return render_template(
            "report.html", month=month, income=income, expenses=expenses,
            net=income - expenses, spending=spending_bars, income_bars=income_bars,
            versus=bars([("Income", income), ("Expenses", expenses)]),
            trend=trend, prev_month=shift_month(month, -1),
            next_month=shift_month(month, 1))

    # ------------------------------------------------------------------ import

    @app.route("/import", methods=["GET", "POST"])
    def import_upload():
        if request.method == "GET":
            return render_template("import_upload.html", errors=[])
        f = request.files.get("file")
        if f is None or not f.filename:
            return render_template("import_upload.html", errors=["Choose a CSV file to upload."]), 400
        text = decode(f.read())
        try:
            header, rows = read_rows(text)
        except (ValueError, csv.Error) as e:
            return render_template("import_upload.html", errors=[f"Could not read the file: {e}."]), 400
        if not rows:
            return render_template("import_upload.html",
                                   errors=["The file has a header row but no transactions."]), 400
        import_id = db.save_pending_import(f.filename[:200], text)
        return redirect(url_for("import_map", import_id=import_id))

    def load_pending(import_id):
        pending = db.get_pending_import(import_id)
        if pending is None:
            abort(404)
        header, rows = read_rows(pending["content"])
        return pending, header, rows

    def map_page(pending, header, rows, sel, errors=(), status=200, profile=None,
                 parsed_preview=None):
        return render_template(
            "import_map.html", pending=pending, header=header,
            preview=rows[:PREVIEW_ROWS], total=len(rows), sel=sel,
            errors=list(errors), date_formats=DATE_FORMATS,
            profile=profile, parsed_preview=parsed_preview), status

    def ncols_of(header, rows):
        return max([len(header)] + [len(c) for _, c in rows])

    def profile_selection(saved, ncols):
        """The usable part of a saved mapping; anything stale or malformed is
        dropped so the guessed value is used instead."""
        sel = {}
        for name in PROFILE_COLS:
            value = saved.get(name)
            if value == "" or (isinstance(value, str) and value.isdigit()
                               and int(value) < ncols):
                sel[name] = value
        if saved.get("date_fmt") in KNOWN_FORMATS:
            sel["date_fmt"] = saved["date_fmt"]
        if saved.get("mode") in ("single", "split"):
            sel["mode"] = saved["mode"]
        if saved.get("decimal") in ("dot", "comma"):
            sel["decimal"] = saved["decimal"]
        if "negate" in saved:
            sel["negate"] = "1" if saved["negate"] else ""
        return sel

    def profile_mapping(form, mapping):
        """What an import profile stores for a validated mapping form."""
        saved = {name: form.get(name, "").strip() for name in PROFILE_COLS}
        saved.update(date_fmt=mapping.date_fmt,
                     mode="split" if mapping.amount_col is None else "single",
                     decimal="comma" if mapping.decimal_comma else "dot",
                     negate=mapping.negate)
        return saved

    @app.get("/import/<int:import_id>")
    def import_map(import_id):
        pending, header, rows = load_pending(import_id)
        g = guess_mapping(header, rows)
        sel = {"date_col": g["date"], "date_fmt": g["date_fmt"], "mode": g["mode"],
               "amount_col": g["amount"], "debit_col": g["debit"],
               "credit_col": g["credit"], "payee_col": g["payee"],
               "note_col": g["note"], "decimal": "dot"}
        sel = {k: ("" if v is None else str(v)) for k, v in sel.items()}
        profile = db.get_import_profile(header)
        if profile is not None:
            sel.update(profile_selection(profile["mapping"], ncols_of(header, rows)))
        sel["remember"] = "1"
        return map_page(pending, header, rows, sel, profile=profile)

    def plan_import(parsed, allow_duplicates):
        """Mark each parsed row as new or duplicate and pick its rule category.
        Returns (new, dupes); nothing is written."""
        dates = [t["date"] for t in parsed]
        existing = db.existing_keys(min(dates), max(dates), dup_key)
        new, dupes = split_duplicates(parsed, existing)
        if allow_duplicates:
            new, dupes = new + dupes, []
        rule_list = rules.load_rules()
        for tx in new:
            tx["category_id"] = rules.pick_category(tx["payee"], rule_list,
                                                    tx["amount_cents"])
        for tx in dupes:
            tx["duplicate"] = True
        return new, dupes

    def preview_rows(parsed, new, dupes):
        """The first parsed rows, in file order, with what importing would do."""
        names = {c["id"]: c["name"] for c in db.list_categories()}
        shown = sorted(new + dupes, key=lambda t: t["line"])[:PARSED_PREVIEW_ROWS]
        return [dict(t, category=names.get(t.get("category_id"), "")) for t in shown]

    @app.post("/import/<int:import_id>")
    def import_commit(import_id):
        pending, header, rows = load_pending(import_id)
        ncols = ncols_of(header, rows)
        mapping, errors = mapping_from_form(request.form, ncols)
        if errors:
            return map_page(pending, header, rows, request.form, errors, 400)
        parsed, row_errors = parse_rows(rows, mapping)
        if not parsed:
            shown = row_errors[:10]
            more = len(row_errors) - len(shown)
            if more:
                shown.append(f"... and {more} more.")
            return map_page(pending, header, rows, request.form,
                            ["No row could be imported with this mapping."] + shown, 400)
        new, dupes = plan_import(parsed, request.form.get("allow_duplicates"))
        if request.form.get("action") == "preview":
            return map_page(pending, header, rows, request.form, profile=None,
                            parsed_preview={
                                "rows": preview_rows(parsed, new, dupes),
                                "parsed": len(parsed), "new": len(new),
                                "duplicates": len(dupes),
                                "errors": row_errors})
        categorised = 0
        for tx in new:
            categorised += tx["category_id"] is not None
            db.insert_transaction(tx, commit=False)
        db.get_db().commit()
        if request.form.get("remember"):
            name = os.path.splitext(pending["filename"])[0] or pending["filename"]
            db.save_import_profile(header, name[:MAX_NAME],
                                   profile_mapping(request.form, mapping))
        db.delete_pending_import(import_id)
        return render_template("import_result.html", filename=pending["filename"],
                               imported=new, duplicates=dupes, errors=row_errors,
                               categorised=categorised)

    # --------------------------------------------------------- import profiles

    @app.get("/import/profiles")
    def import_profiles():
        return render_template("import_profiles.html",
                               profiles=db.list_import_profiles())

    @app.route("/import/profiles/<int:profile_id>", methods=["GET", "POST"])
    def edit_import_profile(profile_id):
        profile = db.get_import_profile_by_id(profile_id)
        if profile is None:
            abort(404)
        header = profile["header"]

        def form_page(sel, errors=(), status=200):
            return render_template("import_profile_form.html", profile=profile,
                                   header=header, sel=sel, errors=list(errors),
                                   date_formats=DATE_FORMATS), status

        if request.method == "GET":
            sel = profile_selection(profile["mapping"], len(header))
            sel["name"] = profile["name"]
            return form_page(sel)
        name, errors = validate_name(request.form)
        mapping, map_errors = mapping_from_form(request.form, len(header))
        errors += map_errors
        if errors:
            return form_page(request.form, errors, 400)
        db.update_import_profile(profile_id, name,
                                 profile_mapping(request.form, mapping))
        flash(f"Saved mapping \"{name}\" updated.")
        return redirect(url_for("import_profiles"))

    @app.post("/import/profiles/<int:profile_id>/delete")
    def delete_import_profile(profile_id):
        if not db.delete_import_profile(profile_id):
            abort(404)
        flash("Saved mapping deleted.")
        return redirect(url_for("import_profiles"))
