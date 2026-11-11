"""Command line entry point: ``budgetbook init`` and ``budgetbook run``."""
import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime

from . import __version__, db, jsonio

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def default_db():
    return os.environ.get("BUDGETBOOK_DB", "budgetbook.db")


def build_parser():
    p = argparse.ArgumentParser(
        prog="budgetbook",
        description="A small local personal-finance web app (Flask + SQLite).")
    p.add_argument("--version", action="version", version=f"budgetbook {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="create the database")
    init.add_argument("--db", default=None,
                      help="database file (default: $BUDGETBOOK_DB or ./budgetbook.db)")
    init.add_argument("--no-categories", action="store_true",
                      help="do not add the starter categories")

    bk = sub.add_parser("backup", help="write a consistent copy of the database")
    bk.add_argument("--db", default=None,
                    help="database file (default: $BUDGETBOOK_DB or ./budgetbook.db)")
    bk.add_argument("--out", default=None,
                    help="backup file (default: budgetbook-backup-YYYYMMDD-HHMMSS.db)")
    bk.add_argument("--force", action="store_true", help="overwrite an existing backup file")

    ex = sub.add_parser("export", help="write everything as one JSON file")
    ex.add_argument("--json", action="store_true", required=True, help="JSON format")
    ex.add_argument("--db", default=None,
                    help="database file (default: $BUDGETBOOK_DB or ./budgetbook.db)")
    ex.add_argument("--out", default=None, help="output file (default: standard output)")

    im = sub.add_parser("import", help="merge a JSON export into the database")
    im.add_argument("--json", metavar="FILE", required=True, help="export file to read")
    im.add_argument("--db", default=None,
                    help="database file (default: $BUDGETBOOK_DB or ./budgetbook.db)")

    run = sub.add_parser("run", help="start the web app")
    run.add_argument("--db", default=None,
                     help="database file (default: $BUDGETBOOK_DB or ./budgetbook.db)")
    run.add_argument("--host", default="127.0.0.1",
                     help="interface to listen on (default: 127.0.0.1)")
    run.add_argument("--port", type=int, default=5000, help="port (default: 5000)")
    run.add_argument("--debug", action="store_true", help="Flask debug mode (never on a network)")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    path = args.db or default_db()

    if args.command == "init":
        existed = os.path.exists(path)
        try:
            seeded = db.init_file(path, seed=not args.no_categories)
        except (OSError, sqlite3.Error) as e:
            print(f"budgetbook: cannot create {path}: {e}", file=sys.stderr)
            return 1
        print(f"{'Database ready' if existed else 'Created database'}: {os.path.abspath(path)}")
        if seeded:
            print(f"Added {len(db.DEFAULT_CATEGORIES)} starter categories.")
        return 0

    if args.command == "backup":
        out = args.out or datetime.now().strftime("budgetbook-backup-%Y%m%d-%H%M%S.db")
        if os.path.abspath(out) == os.path.abspath(path):
            print("budgetbook: the backup file must differ from the database", file=sys.stderr)
            return 2
        if os.path.exists(out) and not args.force:
            print(f"budgetbook: {out} already exists (use --force to overwrite)",
                  file=sys.stderr)
            return 1
        try:
            if os.path.exists(path) and os.path.exists(out):
                os.remove(out)
            count = db.backup_file(path, out)
        except (OSError, sqlite3.Error) as e:
            print(f"budgetbook: backup failed: {e}", file=sys.stderr)
            return 1
        print(f"Backed up {count} transactions to {os.path.abspath(out)}")
        return 0

    if args.command == "export":
        if not os.path.isfile(path):
            print(f"budgetbook: no database at {path}", file=sys.stderr)
            return 1
        conn = db.connect(path)
        try:
            data = jsonio.export_data(conn)
        except sqlite3.Error as e:
            print(f"budgetbook: export failed: {e}", file=sys.stderr)
            return 1
        finally:
            conn.close()
        text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        if args.out is None:
            sys.stdout.write(text)
        else:
            try:
                with open(args.out, "w", encoding="utf-8", newline="\n") as f:
                    f.write(text)
            except OSError as e:
                print(f"budgetbook: cannot write {args.out}: {e}", file=sys.stderr)
                return 1
            print(f"Exported {len(data['transactions'])} transactions to "
                  f"{os.path.abspath(args.out)}")
        return 0

    if args.command == "import":
        try:
            with open(args.json, encoding="utf-8-sig") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            print(f"budgetbook: cannot read {args.json}: {e}", file=sys.stderr)
            return 1
        try:
            db.init_file(path)
            conn = db.connect(path)
            try:
                added, skipped = jsonio.import_data(conn, data)
            finally:
                conn.close()
        except (jsonio.ImportError_, KeyError, TypeError, AttributeError) as e:
            print(f"budgetbook: invalid export file: {e}", file=sys.stderr)
            return 1
        except (OSError, sqlite3.Error) as e:
            print(f"budgetbook: import failed: {e}", file=sys.stderr)
            return 1
        for key in added:
            print(f"{key:<13} {added[key]} added, {skipped[key]} already present")
        return 0

    if args.command == "run":
        if not 0 < args.port < 65536:
            print("budgetbook: --port must be between 1 and 65535", file=sys.stderr)
            return 2
        if args.host not in LOCAL_HOSTS:
            print(f"budgetbook: warning: listening on {args.host}; budgetbook has no "
                  "login, so anyone who can reach this address can see your data.",
                  file=sys.stderr)
        from . import create_app
        try:
            app = create_app({"DATABASE": path})
        except (OSError, sqlite3.Error) as e:
            print(f"budgetbook: cannot open {path}: {e}", file=sys.stderr)
            return 1
        print(f"budgetbook {__version__} using {os.path.abspath(path)}")
        app.run(host=args.host, port=args.port, debug=args.debug)
        return 0
    return 2  # pragma: no cover - argparse enforces a command
