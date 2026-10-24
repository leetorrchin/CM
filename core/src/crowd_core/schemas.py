"""Load the JSON Schemas in schemas/ and validate documents against them."""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

KINDS = {
    "venue": "venue.schema.json",
    "entity": "entity.schema.json",
    "position_update": "position_update.schema.json",
    "group": "group.schema.json",
    "occupancy_reading": "occupancy_reading.schema.json",
    "plan": "plan.schema.json",
    "scenario": "scenario.schema.json",
    "event": "event.schema.json",
}


def schemas_dir() -> Path:
    env = os.environ.get("CROWD_SCHEMAS_DIR")
    if env:
        return Path(env)
    # core/src/crowd_core/schemas.py -> repo root is parents[3]
    return Path(__file__).resolve().parents[3] / "schemas"


@lru_cache(maxsize=1)
def _registry() -> Registry:
    resources = []
    for path in sorted(schemas_dir().glob("*.schema.json")):
        doc = json.loads(path.read_text())
        resources.append((doc["$id"], Resource.from_contents(doc)))
    return Registry().with_resources(resources)


def validator(kind: str) -> Draft202012Validator:
    doc = json.loads((schemas_dir() / KINDS[kind]).read_text())
    return Draft202012Validator(doc, registry=_registry())


def schema_errors(kind: str, document: Any) -> list[str]:
    """Return human-readable schema errors (empty list means valid)."""
    errors = sorted(validator(kind).iter_errors(document), key=lambda e: list(e.absolute_path))
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}" for e in errors]
