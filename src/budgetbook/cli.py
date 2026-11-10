"""Command line entry point: ``budgetbook init`` and ``budgetbook run``."""
import argparse
import os
import sqlite3
import sys

from . import __version__, db

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
