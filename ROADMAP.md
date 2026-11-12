# Roadmap

Estimates are rough working hours for one person.

## v0.1 (done)

- [x] Transactions with date, integer-cent amount, payee, category and note;
      add, edit, delete, filter by month, category and search; CSV export
- [x] Categories: add, rename, delete (transactions become uncategorised)
- [x] Bank CSV import with a column-mapping step, date-format detection,
      debit/credit columns, decimal comma, sign flip, per-line error report
- [x] Duplicate detection on date + amount + payee, counting copies
- [x] Rules: payee contains X → category Y, longest match wins
- [x] Monthly budgets per category that carry forward, spent/remaining
- [x] Monthly report with inline-SVG bars and a six-month trend
- [x] CSRF tokens on every form, autoescaped output
- [x] `budgetbook init` / `budgetbook run`; pytest suite; CI on Ubuntu and Windows

## v0.2: saved import profiles (done)

- [x] Remember the column mapping per bank (keyed by the header row) and
      preselect it on the next upload
- [x] Name, edit and delete saved profiles
- [x] Preview the first parsed rows (date, amount, payee) before committing

## v0.3: better rules (about 3 h)

- [x] Match types besides "contains": starts with, exact, and a regex option
      with validation
- [x] Optional amount range on a rule (e.g. only spending over 100.00)
- [x] "Create rule from this transaction" link on the transaction list
- [x] Re-run rules over already categorised transactions, with a preview of
      what would change

## v0.4: accounts and transfers (about 4 h, split in two)

Part 1 (about 1 h): accounts and the account on a transaction.

- [x] Accounts (current, savings, credit card) with an opening balance;
      account on each transaction, filter and balance per account; safe
      migration of older databases

Part 2:

- [x] Choose the account when importing; running balance per account
- [x] Mark a pair of transactions as a transfer so it is left out of income
      and expenses (schema version 6; JSON export/import does not carry the
      link yet)

## v0.5: split transactions (about 3 h)

- [ ] Split one transaction across several categories with amounts that must
      add up to the total
- [ ] Budgets and the report use the split amounts

## v0.6: yearly view and trends (about 3 h)

- [x] Year report: month-by-month table per category with totals
- [x] Average monthly spend per category over the last 3, 6 and 12 months
- [x] Budget suggestions based on those averages

## v0.7: backups and data portability (about 2 h)

- [x] `budgetbook backup` writes a consistent copy using SQLite's backup API
- [x] `budgetbook export --json` and a matching `import --json` for moving
      everything (categories, rules, budgets, transactions) between machines

## v0.8: quality of life (about 2 h)

- [x] Pagination on the transaction list for large histories
- [x] Bulk select to set the category or delete several transactions at once
- [x] Remember the last month and filters you viewed
