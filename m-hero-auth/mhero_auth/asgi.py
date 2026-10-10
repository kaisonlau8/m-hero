"""Pure-ASGI middleware (FastAPI / Starlette)."""
from __future__ import annotations

import json
from urllib.parse import parse_qsl

from .core import AuthConfig, Authenticator, Request


class AuthMiddleware:
    def __init__(self, app, app_name: str, **overrides):
        self.app = app
        self.auth = Authenticator(AuthConfig.from_env(app_name, **overrides))

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":          # websockets etc: only allowed when auth is off
            if scope["type"] == "websocket" and self.auth.effective_mode() == "on":
                await send({"type": "websocket.close", "code": 1008})
                return
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        cookies = {}
        for part in headers.get("cookie", "").split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                cookies[k] = v
        client = scope.get("client") or ("", 0)
        req = Request(scope["method"], scope["path"], headers, cookies,
                      dict(parse_qsl(scope.get("query_string", b"").decode())), client[0])
        d = self.auth.authorize(req)
        scope.setdefault("state", {})["mhero_session"] = d.session
        if d.kind == "allow" and d.json_body is None:
            await self.app(scope, receive, send)
            return
        out = [(b"cache-control", b"no-store")]
        if d.kind == "redirect":
            out.append((b"location", d.location.encode()))
            body = b""
        elif d.json_body is not None and (d.kind == "allow" or self.auth.wants_json(req)):
            body = json.dumps(d.json_body).encode()
            out.append((b"content-type", b"application/json"))
        else:
            body = (d.body or "unauthorized").encode()
            out.append((b"content-type", b"text/plain; charset=utf-8"))
        for c in d.set_cookies:
            out.append((b"set-cookie", c.encode()))
        await send({"type": "http.response.start", "status": d.status, "headers": out})
        await send({"type": "http.response.body", "body": body})
