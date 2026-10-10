"""In-memory stand-in for CasdoorAdmin (same interface AccountService uses)."""
from mhero_auth.casdoor_admin import CasdoorError


class FakeCasdoor:
    org = "mhero"

    def __init__(self):
        self.users = {}          # name -> dict
        self.roles = {}          # role -> set(names)
        self.pw = {}             # never asserted on in logs
        self.calls = []

    def seed(self, name, level="", apps=(), disabled=False, display=None):
        self.users[name] = {"name": name, "displayName": display or name, "isForbidden": disabled, "needUpdatePassword": False, "email": ""}
        if level:
            self.roles.setdefault(f"mhero-{level}", set()).add(name)
        for a in apps:
            self.roles.setdefault(f"mhero-app-{a}", set()).add(name)

    def list_users(self): return [dict(u) for u in self.users.values()]
    def get_user(self, name): return dict(self.users[name]) if name in self.users else None
    def list_roles(self): return {r: {"name": r, "users": [f"mhero/{u}" for u in sorted(us)]} for r, us in self.roles.items()}

    def set_membership(self, role, user, present):
        self.calls.append(("member", role, user, present))
        s = self.roles.setdefault(role, set())
        before = user in s
        (s.add if present else s.discard)(user)
        return before != present

    def add_user(self, name, display, password, *, need_update_password=True, email=""):
        self.calls.append(("add_user", name))
        if name in self.users:
            raise CasdoorError("exists")
        self.pw[name] = password
        self.users[name] = {"name": name, "displayName": display, "isForbidden": False, "needUpdatePassword": need_update_password, "email": email}

    def set_password(self, name, password, *, need_update_password=True):
        self.pw[name] = password
        self.users[name]["needUpdatePassword"] = need_update_password

    def set_forbidden(self, name, forbidden):
        self.users[name]["isForbidden"] = forbidden
