"""mhero_auth — shared Casdoor (OIDC) login for m-hero web consoles.

Flask:   from mhero_auth.flask_adapter import init_app;  init_app(app, "hub")
FastAPI: from mhero_auth.asgi import AuthMiddleware;   app.add_middleware(AuthMiddleware, app_name="reportdb")
"""
from .core import AuthConfig, Authenticator, Decision, Request, Session  # noqa: F401

__version__ = "0.1.0"
