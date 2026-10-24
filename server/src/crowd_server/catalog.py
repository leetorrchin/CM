"""Where venues and scenarios live, and how to load them safely."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from crowd_core.scenario import scenario_errors
from crowd_core.venue import validate_venue
from crowd_sim.autoscenario import auto_scenario

ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def find_root() -> Path:
    if os.environ.get("CROWD_ROOT"):
        return Path(os.environ["CROWD_ROOT"]).resolve()
    here = Path(__file__).resolve()
    for p in here.parents:
        if (p / "venues").is_dir() and (p / "scenarios").is_dir():
            return p
    return Path.cwd()


class Catalog:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or find_root()).resolve()
        self.user_dir = self.root / "venues" / "user"

    # ---- venues
    def _venue_files(self) -> dict[str, tuple[Path, str]]:
        out: dict[str, tuple[Path, str]] = {}
        for sub, source in (("", "example"), ("generated", "generated"), ("user", "user")):
            d = self.root / "venues" / sub if sub else self.root / "venues"
            if d.is_dir():
                for f in sorted(d.glob("*.json")):
                    out[f.stem] = (f, source)
        return out

    def list_venues(self) -> list[dict[str, str]]:
        res = []
        for vid, (f, source) in self._venue_files().items():
            try:
                name = json.loads(f.read_text()).get("name", vid)
            except (OSError, ValueError):
                continue
            res.append({"id": vid, "name": name, "source": source})
        return res

    def get_venue(self, vid: str) -> dict[str, Any]:
        if not ID_RE.match(vid):
            raise KeyError(vid)
        files = self._venue_files()
        if vid not in files:
            raise KeyError(vid)
        return json.loads(files[vid][0].read_text())

    def save_user_venue(self, venue: dict[str, Any]) -> list[str]:
        errs = validate_venue(venue)
        vid = venue.get("id", "")
        if not errs and not ID_RE.match(str(vid)):
            errs = [f"venue id '{vid}' must be lowercase letters, digits, - or _"]
        if errs:
            return errs
        self.user_dir.mkdir(parents=True, exist_ok=True)
        (self.user_dir / f"{vid}.json").write_text(json.dumps(venue, indent=2))
        return []

    # ---- scenarios
    def list_scenarios(self, venue_id: str) -> list[str]:
        names = ["auto-egress"]
        for d in (self.root / "scenarios", self.root / "scenarios" / "generated" / venue_id):
            if d.is_dir():
                for f in sorted(d.glob("*.json")):
                    try:
                        if json.loads(f.read_text()).get("venue") == venue_id and f.stem not in names:
                            names.append(f.stem)
                    except (OSError, ValueError):
                        pass
        return names

    def get_scenario(self, venue: dict[str, Any], name: str, total: int | None) -> dict[str, Any]:
        sc = None
        if name == "auto-egress":
            sc = auto_scenario(venue, total or 3000)
        else:
            for d in (self.root / "scenarios", self.root / "scenarios" / "generated" / venue["id"]):
                f = d / f"{name}.json"
                if ID_RE.match(name) and f.is_file():
                    sc = json.loads(f.read_text())
                    break
        if sc is None:
            raise KeyError(name)
        if total is not None:
            sc["crowd"]["total"] = total
        errs = scenario_errors(sc, venue)
        if errs:
            raise ValueError("; ".join(errs))
        return sc
