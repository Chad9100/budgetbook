# budgetbook

A small personal-finance web app that runs on your own computer. Record
transactions by hand or import your bank's CSV export, let simple rules
categorise them, set a monthly budget per category, and see where the money
went on a monthly report.

**Who it is for:** people who want a private, no-account budget tool whose data
is a single SQLite file they own, without a spreadsheet full of formulas.

**Built with:** Python 3.10+, Flask (the only runtime dependency) and the
standard-library `sqlite3`. Pages are plain server-rendered HTML; the charts
are inline SVG, with no JavaScript framework. Tests use pytest.

## Install

```sh
git clone https://github.com/Chad9100/budgetbook.git
cd budgetbook
python -m pip install .
```

That puts a `budgetbook` command on your PATH. `python -m budgetbook` works too.

## Usage

```sh
budgetbook init                 # create ./budgetbook.db with starter categories
budgetbook run                  # serve on http://127.0.0.1:5000
```

Then open <http://127.0.0.1:5000> in a browser.

| Command | Options |
| --- | --- |
| `budgetbook init` | `--db PATH`, `--no-categories` (start with no categories) |
| `budgetbook run` | `--db PATH`, `--host` (default `127.0.0.1`), `--port` (default `5000`), `--debug` |
| `budgetbook backup` | `--db PATH`, `--out FILE` (default `budgetbook-backup-YYYYMMDD-HHMMSS.db` in the current folder), `--force` (overwrite) |
| `budgetbook export --json` | `--db PATH`, `--out FILE` (default: standard output) |
| `budgetbook import --json FILE` | `--db PATH` (created if missing) |

The database path defaults to `$BUDGETBOOK_DB`, or `budgetbook.db` in the
current folder. `run` creates the database if it does not exist yet (without
starter categories). budgetbook has no login, so it listens on localhost only
unless you pass `--host`, and then it prints a warning.

A random session key is stored next to the database as `<db>.secret` (set
`BUDGETBOOK_SECRET` to use your own). `budgetbook backup` writes a consistent
copy of the database using SQLite's backup API, so it is safe to run while the
app is serving; it never overwrites an existing file without `--force`. It
does not copy the `.secret` file (a new one is made on first run).

`export --json` writes categories, accounts, rules, budgets and transactions
as one UTF-8 JSON file that refers to categories and accounts by name, so it
can be imported into a database with different ids. `import --json` merges: names
that already exist are reused (case-insensitively) and rules, budgets and
transactions already present are skipped, so importing the same file twice
adds nothing. The whole import is one transaction; an invalid file changes
nothing. Real output for a small database, imported twice into a new one:

```text
$ budgetbook export --json --db a.db --out all.json
Exported 2 transactions to .../all.json
$ budgetbook import --json all.json --db b.db
categories    10 added, 0 already present
accounts      1 added, 0 already present
rules         0 added, 0 already present
budgets       1 added, 0 already present
transactions  2 added, 0 already present
$ budgetbook import --json all.json --db b.db
categories    0 added, 10 already present
accounts      0 added, 1 already present
rules         0 added, 0 already present
budgets       0 added, 1 already present
transactions  0 added, 2 already present
```

To try it with sample data, import [examples/bank-statement.csv](examples/bank-statement.csv).

## Features

- **Transactions:** add, edit and delete transactions with a date, amount,
  payee, category and note. Filter by month, category (or "uncategorised")
  and a search over payee and note. Export the list (or one month) as CSV.
  The list shows 50 transactions per page with Newer/Older links that keep
  your filters; the totals line always covers every match, not just the
  page. With 120 transactions, real output of the pager line:
  `Showing 1-50 of 120 (page 1 of 3)`, then `Showing 101-120 of 120 (page 3
  of 3)` on the last page. An out-of-range page number is clamped.
- **Remembered filters:** the list remembers the month, category, account
  and search you last used (in your browser session), so opening
  "Transactions" again returns to them. The "All" link forgets them
  (`/?clear=1`). Real output with a September and an October payment, which
  payees appear after each request: `/?month=2026-09` shows `Septshop`; a
  bare `/` afterwards still shows only `Septshop`; `/?clear=1` shows
  `Septshop` and `Octshop`, and so does the next bare `/`.
- **Bulk actions:** every row has a checkbox (the header one ticks the whole
  page). Under the table, "Set category" applies a category, or
  "Uncategorised", to all ticked transactions and "Delete" removes them after
  a confirmation. You return to the same filters and page. Real flash
  messages from three ticked coffees and one deleted rent payment:
  `Set 3 transactions to Eating out.`, then `Deleted 1 transaction.`
  Nothing ticked changes nothing.
- **Accounts:** add accounts (current, savings, credit card, cash) with an
  opening balance; the Accounts page shows each balance (opening plus its
  transactions). Pick an account on a transaction and filter the list by
  account. Older databases upgrade in place and keep their transactions with
  no account. Transfers come later. When you have accounts, the import
  mapping step has an "Account for these transactions" menu, and every
  imported row is stored on the account you pick (default: no account).
  Filtering the transaction list by one account adds a Balance column: the
  balance right after each transaction (opening balance plus all earlier
  transactions in date order), shown even when other filters hide rows. With
  a 1000.00 opening balance and the sample statement imported into it, real
  output for the newest rows (date, payee, amount, balance):
  `2026-10-28 THE CORNER CAFE -4.80 2,643.97`, then
  `2026-10-26 AMAZON MARKETPLACE +9.99 2,648.77`, then
  `2026-10-24 AMAZON MARKETPLACE -23.99 2,638.78`.
- **Money as integer cents.** Amounts are stored as integer cents (negative
  means money out), so totals are exact. The forms accept `1,234.56`, `$12`,
  `(12.00)` and similar. An ambiguous value such as `12,50` is rejected
  rather than guessed.
- **Bank CSV import in two steps.** Upload the file, then map its columns: date
  (with the format detected from the data), one signed amount column or
  separate debit/credit columns, payee and an optional note. Comma or semicolon
  delimiters, `1.234,56` decimals, a "flip signs" option, UTF-8 with or without
  a BOM, and Windows-1252 are all handled. Rows that fail to parse are listed
  with their line number, and the rest import.
- **Preview before importing.** On the mapping step, Preview parses the file
  with the chosen mapping and shows the first ten rows as they would be
  stored (date, signed amount, payee, the category a rule would give, and
  whether the row is new or a skipped duplicate), plus how many rows would be
  added, skipped or rejected. Nothing is written until you press Import.
- **Remembered import mappings.** After a successful import the column
  mapping (columns, date format, decimal separator, flip signs) is saved for
  that bank, keyed by the file's header row ignoring case and spacing. The
  next file with the same columns opens with that mapping preselected. Untick
  "Remember this mapping" to skip saving; saving again replaces the old one.
  The Saved mappings page (linked from Import) lists them; rename one, adjust
  its columns, date format and options, or delete it.
- **Duplicate detection.** A row with the same date, amount and payee
  (ignoring case and spacing) as a stored transaction is skipped, so
  re-importing an overlapping statement is safe. It counts copies: if the file
  has two identical coffees on one day and only one is stored, one new
  transaction is imported. A checkbox imports duplicates anyway.
- **Rules:** "payee contains X → category Y", case-insensitive. A rule can
  instead match when the payee *starts with* X, *is exactly* X, or *matches
  a regular expression* (checked when you save it; searched anywhere in the
  payee, case-insensitive). When several rules match, an exact rule wins,
  then the longest "contains"/"starts with" pattern, then a regex rule; ties
  go to the rule created first. Rules apply to imports, to transactions saved
  without a category, and to every uncategorised transaction with one button.
  A rule can also have an optional amount range (size only, sign ignored),
  so e.g. only payments of 100.00 or more are categorised; among equally
  specific rules the one with a range wins. Rules from older databases are
  upgraded in place as unlimited "contains" rules. The "Make rule" link on
  each transaction opens the rule form prefilled with its payee and category.
  "Preview re-running rules" on the Rules page lists already categorised
  transactions whose category the current rules would change; you untick any
  to keep and apply the rest (transactions no rule matches are never touched).
- **Monthly budgets** per category with spent, remaining and a usage bar.
  A budget carries forward to later months until you change it. Spending is
  the category's net total, so a refund lowers it.
- **Monthly report:** income, expenses and net; income-vs-expenses bars;
  spending per category next to its budget; income per category; and a
  six-month income/expenses trend, all drawn as inline SVG.
- **Safe by default:** every form that changes data carries a per-session CSRF
  token, and the session cookie is `SameSite=Lax` and `HttpOnly`. All output
  is escaped by Jinja autoescaping. Exported CSV cells that start with `=`,
  `+`, `-` or `@` are prefixed so spreadsheet apps do not run them as formulas.

## Development

```sh
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"   # .venv/bin/python on Linux/macOS
.venv/Scripts/pytest -q
```

Tests use Flask's test client against a temporary database. CI runs them on
Ubuntu and Windows with Python 3.10, 3.12 and 3.13.

See [ROADMAP.md](ROADMAP.md) for planned work.

## License

MIT, see [LICENSE](LICENSE).
