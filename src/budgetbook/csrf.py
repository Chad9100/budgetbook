"""Minimal session-based CSRF protection (no extra dependency).

Every session gets a random token. Every state-changing request must send it
back as the ``csrf_token`` form field; templates add it with ``csrf_field()``.
"""
import hmac
import secrets

from flask import abort, request, session
from markupsafe import Markup, escape

FIELD = "csrf_token"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def init_app(app):
    @app.before_request
    def _check_csrf():
        token = session.get(FIELD)
        if not token:
            token = session[FIELD] = secrets.token_urlsafe(32)
        if request.method in UNSAFE_METHODS:
            sent = request.form.get(FIELD, "")
            if not hmac.compare_digest(sent.encode(), token.encode()):
                abort(400, description="The form has expired or is invalid. "
                                       "Go back, reload the page and try again.")

    def csrf_field():
        return Markup('<input type="hidden" name="%s" value="%s">'
                      % (FIELD, escape(session.get(FIELD, ""))))

    app.jinja_env.globals["csrf_field"] = csrf_field
