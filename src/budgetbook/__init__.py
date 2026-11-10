"""budgetbook: a small local personal-finance web app (Flask + SQLite)."""
import os
import secrets

from flask import Flask

from . import csrf, db
from .money import cents_to_input, format_cents, month_label

__version__ = "0.1.0"


def load_or_create_secret(db_path):
    """Keep a random session key next to the database so forms survive
    restarts without shipping a hard-coded key."""
    path = os.path.abspath(db_path) + ".secret"
    try:
        with open(path, encoding="ascii") as f:
            key = f.read().strip()
        if key:
            return key
    except FileNotFoundError:
        pass
    key = secrets.token_hex(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as f:
        f.write(key)
    return key


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        DATABASE=os.environ.get("BUDGETBOOK_DB", "budgetbook.db"),
        MAX_CONTENT_LENGTH=5 * 1024 * 1024,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_HTTPONLY=True,
    )
    if test_config:
        app.config.update(test_config)
    db.init_file(app.config["DATABASE"])
    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = (os.environ.get("BUDGETBOOK_SECRET")
                                    or load_or_create_secret(app.config["DATABASE"]))
    app.teardown_appcontext(db.close_db)
    csrf.init_app(app)

    app.add_template_filter(format_cents, "money")
    app.add_template_filter(lambda c: format_cents(c, signed=True), "signed_money")
    app.add_template_filter(cents_to_input, "plain_money")
    app.add_template_filter(month_label, "month_label")

    from . import views
    views.register(app)
    return app
