"""Server settings, read from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _flag(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    return default if v is None else v.strip().lower() not in ("0", "false", "off", "no", "")


@dataclass
class Settings:
    root: Path
    data_dir: Path
    auth: bool = True               # CROWD_AUTH=off turns logins off (local demos, tests)
    max_sessions: int = 6           # CROWD_MAX_SESSIONS
    max_total_people: int = 120_000  # CROWD_MAX_PEOPLE across all sessions
    token_ttl_s: int = 12 * 3600
    static_dir: Path | None = None
    autostart: bool = True

    @classmethod
    def from_env(cls, root: Path) -> "Settings":
        data = Path(os.environ.get("CROWD_DATA", root / "data"))
        static = os.environ.get("CROWD_STATIC")
        return cls(
            root=root, data_dir=data, auth=_flag("CROWD_AUTH", True),
            max_sessions=int(os.environ.get("CROWD_MAX_SESSIONS", "6")),
            max_total_people=int(os.environ.get("CROWD_MAX_PEOPLE", "120000")),
            token_ttl_s=int(os.environ.get("CROWD_TOKEN_TTL_S", str(12 * 3600))),
            static_dir=Path(static) if static else root / "viz" / "dist",
            autostart=_flag("CROWD_AUTOSTART", True))
