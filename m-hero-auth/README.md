# mhero_auth — shared Casdoor SSO for m-hero consoles
See `../docs/SSO_CASDOOR.md`. Quick use:

```python
# Flask (hub, vip, district, cleaner, nss, accident)
from mhero_auth.flask_adapter import init_app
init_app(app, "hub", public_get_paths=["/healthz"])

# FastAPI (reportdb, district app/main.py)
from mhero_auth.asgi import AuthMiddleware
app.add_middleware(AuthMiddleware, app_name="reportdb", public_get_paths=["/healthz"])
```
Config is all env (`MHERO_AUTH`, `MHERO_AUTH_ISSUER`, `..._CLIENT_ID/_SECRET`, `..._BASE_URL`, `..._SESSION_SECRET`, ...).
`MHERO_AUTH=off|audit|on`, or `touch $MHERO_AUTH_OFF_FILE` to disable instantly. Tests: `PYTHONPATH=. pytest` (28 tests; the
Casdoor integration ones auto-skip unless a dev Casdoor is running on :18000).
