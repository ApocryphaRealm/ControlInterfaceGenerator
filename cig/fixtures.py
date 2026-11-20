"""Fixtures: recorded UI tree snapshots (library/schema/fixture.schema.json)."""
from __future__ import annotations

import datetime
import json
from pathlib import Path

import jsonschema

from . import config

SCHEMA_PATH = config.LIBRARY_DIR / "schema" / "fixture.schema.json"


def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def validate(data: dict) -> None:
    jsonschema.validate(data, schema())


def load(path: str | Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    validate(data)
    return data


def save(data: dict, path: str | Path) -> Path:
    data.setdefault("cig_fixture", 1)
    data.setdefault("captured", datetime.datetime.now().astimezone().isoformat(timespec="seconds"))
    validate(data)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    return p
