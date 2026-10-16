"""Flask adapter: one before_request hook + after_request cookie writer."""
from __future__ import annotations

from flask import Response, g, jsonify, request

import os

from .userbar import inject, userbar_html
from .core import AuthConfig, Authenticator, Request


def _req() -> Request:
    return Request(request.method, request.path, {k.lower(): v for k, v in request.headers.items()},
                   dict(request.cookies), request.args.to_dict(), request.remote_addr or "")


def init_app(app, app_name: str, **overrides) -> Authenticator:
    """Protect a Flask app. overrides: public_paths=[...], public_get_paths=[...], admin_paths=[...], read_role=..."""
    userbar = overrides.pop("userbar", None)
    bar_account = overrides.pop("userbar_account_url", "")          # e.g. "/account" on the hub (default: cfg.account_url)
    bar_accounts = overrides.pop("userbar_accounts_url", "")        # admin 「账号管理」 link; "" = not shown
    if userbar is None:
        userbar = os.environ.get("MHERO_AUTH_USERBAR", "") in ("1", "true", "yes")
    auth = Authenticator(AuthConfig.from_env(app_name, **overrides))
    app.extensions["mhero_auth"] = auth

    @app.before_request
    def _mhero_auth_gate():
        d = auth.authorize(_req())
        g.mhero_session = d.session
        if d.kind == "allow" and d.json_body is None:
            return None
        if d.kind == "redirect":
            resp = Response("", status=d.status, headers={"Location": d.location})
        elif d.json_body is not None and (d.kind == "allow" or auth.wants_json(_req())):
            resp = jsonify(d.json_body)
            resp.status_code = d.status
        elif d.html:
            resp = Response(d.html, status=d.status, mimetype="text/html")
            resp.headers["Cache-Control"] = "no-store"
        else:
            resp = Response(d.body or "unauthorized", status=d.status, mimetype="text/plain; charset=utf-8")
        for c in d.set_cookies:
            resp.headers.add("Set-Cookie", c)
        return resp

    @app.context_processor
    def _inject():
        return {"mhero_user": getattr(g, "mhero_session", None)}

    if userbar:
        @app.after_request
        def _mhero_userbar(resp):
            try:
                if resp.status_code == 200 and (resp.mimetype or "") == "text/html" and not resp.direct_passthrough:
                    bar = userbar_html(getattr(g, "mhero_session", None), auth.cfg, auth.effective_mode(), bar_accounts, bar_account)
                    if bar:
                        resp.set_data(inject(resp.get_data(as_text=True), bar))
            except Exception:       # never break a page because of the bar
                pass
            return resp

    return auth


def current_user():
    return getattr(g, "mhero_session", None)
