"""Accounts, signed tokens and login throttling. Standard library only.

Roles: `operator` can control sessions and edit venues; `viewer` can only watch.
Passwords are stored as scrypt hashes in <data>/users.json. Tokens are HMAC-signed with a key in
<data>/secret.key (created on first run) and expire.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from pathlib import Path

ROLES = ("operator", "viewer")
USERNAME_OK = set("abcdefghijklmnopqrstuvwxyz0123456789_-.")


def _hash(password: str, salt: bytes) -> str:
    return hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32).hex()


class Users:
    def __init__(self, data_dir: Path) -> None:
        self.path = Path(data_dir) / "users.json"
        self._lock = threading.Lock()
        self._users: dict[str, dict] = {}
        if self.path.exists():
            self._users = json.loads(self.path.read_text())

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._users, indent=2))
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)

    def __len__(self) -> int:
        return len(self._users)

    def names(self) -> list[tuple[str, str]]:
        return sorted((n, u["role"]) for n, u in self._users.items())

    def add(self, username: str, password: str, role: str = "operator") -> None:
        username = username.strip().lower()
        if not username or not set(username) <= USERNAME_OK or len(username) > 32:
            raise ValueError("username must be 1 to 32 characters: letters, digits, _ - .")
        if role not in ROLES:
            raise ValueError(f"role must be one of {ROLES}")
        if len(password) < 8:
            raise ValueError("password must be at least 8 characters")
        salt = secrets.token_bytes(16)
        with self._lock:
            self._users[username] = {"salt": salt.hex(), "hash": _hash(password, salt), "role": role}
            self._save()

    def remove(self, username: str) -> bool:
        with self._lock:
            gone = self._users.pop(username.strip().lower(), None) is not None
            if gone:
                self._save()
            return gone

    def verify(self, username: str, password: str) -> str | None:
        """Role if the credentials are right, else None. Takes the same time either way."""
        u = self._users.get(username.strip().lower())
        salt = bytes.fromhex(u["salt"]) if u else b"\0" * 16
        ok = hmac.compare_digest(_hash(password, salt), u["hash"] if u else "0" * 64)
        return u["role"] if u and ok else None


class Tokens:
    def __init__(self, data_dir: Path, ttl_s: int) -> None:
        key_path = Path(data_dir) / "secret.key"
        if key_path.exists():
            self._key = key_path.read_bytes()
        else:
            key_path.parent.mkdir(parents=True, exist_ok=True)
            self._key = secrets.token_bytes(32)
            key_path.write_bytes(self._key)
            os.chmod(key_path, 0o600)
        self.ttl = ttl_s

    def _sig(self, body: bytes) -> str:
        return base64.urlsafe_b64encode(hmac.new(self._key, body, hashlib.sha256).digest()).decode().rstrip("=")

    def issue(self, username: str, role: str) -> tuple[str, int]:
        exp = int(time.time()) + self.ttl
        body = base64.urlsafe_b64encode(json.dumps({"u": username, "r": role, "e": exp}).encode()).rstrip(b"=")
        return f"{body.decode()}.{self._sig(body)}", exp

    def verify(self, token: str | None) -> dict | None:
        if not token or token.count(".") != 1:
            return None
        body, sig = token.split(".")
        if not hmac.compare_digest(sig, self._sig(body.encode())):
            return None
        try:
            data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        except ValueError:
            return None
        if data.get("e", 0) < time.time() or data.get("r") not in ROLES:
            return None
        return {"user": data["u"], "role": data["r"], "exp": data["e"]}


class Throttle:
    """Lock an address out for a while after repeated failed logins."""

    def __init__(self, max_fails: int = 5, window_s: int = 300) -> None:
        self.max, self.window = max_fails, window_s
        self._fails: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def blocked(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            hits = [t for t in self._fails.get(key, []) if now - t < self.window]
            self._fails[key] = hits
            return len(hits) >= self.max

    def fail(self, key: str) -> None:
        with self._lock:
            self._fails.setdefault(key, []).append(time.time())

    def ok(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)


def main() -> None:
    """python -m crowd_server.auth add|remove|list [username] [--role operator|viewer]"""
    import argparse
    import getpass

    from .catalog import find_root
    from .settings import Settings

    ap = argparse.ArgumentParser(prog="crowd_server.auth")
    ap.add_argument("cmd", choices=["add", "remove", "list"])
    ap.add_argument("username", nargs="?")
    ap.add_argument("--role", default="operator", choices=ROLES)
    ap.add_argument("--password", help="avoid: shows up in shell history; omit to be prompted")
    a = ap.parse_args()
    users = Users(Settings.from_env(find_root()).data_dir)
    if a.cmd == "list":
        for n, r in users.names():
            print(f"{n}\t{r}")
    elif not a.username:
        ap.error("username required")
    elif a.cmd == "remove":
        print("removed" if users.remove(a.username) else "no such user")
    else:
        pw = a.password or getpass.getpass("Password: ")
        users.add(a.username, pw, a.role)
        print(f"saved {a.username} ({a.role})")


if __name__ == "__main__":
    main()
