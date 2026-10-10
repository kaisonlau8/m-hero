import base64, json, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

SECRET = "s" * 40


def b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


class MockOIDC:
    """Tiny OIDC provider: JWKS + token endpoint that returns whatever ID-token claims we queue."""

    def __init__(self):
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.claims = {}
        self.sign_with = self.key
        outer = self
        n = self.key.public_key().public_numbers()

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_GET(self):
                doc = {"keys": [{"kty": "RSA", "kid": "k1", "alg": "RS256", "use": "sig",
                                 "n": b64(n.n.to_bytes(256, "big")), "e": b64(n.e.to_bytes(3, "big"))}]}
                self._send(doc)
            def do_POST(self):
                self.rfile.read(int(self.headers.get("content-length", 0)))
                self._send({"id_token": outer.mint(), "access_token": "x"})
            def _send(self, d):
                b = json.dumps(d).encode()
                self.send_response(200); self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(b))); self.end_headers(); self.wfile.write(b)

        self.srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_port}"

    def mint(self, **over):
        c = {"iss": self.url, "aud": ["cid"], "exp": time.time() + 3600, "nbf": time.time() - 5, "sub": "u1",
             "name": "alice", "owner": "mhero", "roles": [{"name": "mhero-admin"}], "nonce": self.nonce}
        c.update(self.claims); c.update(over)
        h = b64(json.dumps({"alg": "RS256", "kid": "k1", "typ": "JWT"}).encode())
        p = b64(json.dumps(c).encode())
        sig = self.sign_with.sign(f"{h}.{p}".encode(), padding.PKCS1v15(), hashes.SHA256())
        return f"{h}.{p}.{b64(sig)}"

    nonce = ""


@pytest.fixture(scope="module")
def oidc():
    return MockOIDC()


@pytest.fixture
def env(oidc):
    return {"MHERO_AUTH": "on", "MHERO_AUTH_ISSUER": oidc.url, "MHERO_AUTH_CLIENT_ID": "cid", "MHERO_AUTH_CLIENT_SECRET": "csec",
            "MHERO_AUTH_BASE_URL": "https://app.example.test", "MHERO_AUTH_SESSION_SECRET": SECRET,
            "MHERO_AUTH_ORG": "mhero"}
