"""Event log writer (JSON Lines, one record per line, see schemas/event.schema.json)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from crowd_core.schemas import schema_errors

from .clock import SimClock

SCHEMA_VERSION = "0.1.0"


class EventLog:
    def __init__(self, path: str | Path | None, run_id: str, clock: SimClock,
                 validate: bool = False) -> None:
        self.run_id, self.clock, self.validate, self.seq = run_id, clock, validate, 0
        self._fh = None
        if path is not None:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(path, "w", encoding="utf-8")

    def emit(self, type_: str, data: dict[str, Any]) -> None:
        if self._fh is None:
            return
        rec = {"schema_version": SCHEMA_VERSION, "run_id": self.run_id, "seq": self.seq,
               "timestamp": self.clock.iso(), "type": type_, "data": data}
        if self.validate:
            errs = schema_errors("event", rec)
            if errs:
                raise ValueError(f"invalid event {rec['seq']} ({type_}): {errs}")
        self._fh.write(json.dumps(rec, separators=(",", ":")) + "\n")
        self.seq += 1

    def close(self) -> None:
        if self._fh:
            self._fh.close()
            self._fh = None
