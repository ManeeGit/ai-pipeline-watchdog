from __future__ import annotations

import json
import math
import re
from pathlib import Path

from .models import Pipeline

MAX_BYTES = 25 * 1024 * 1024
MAX_ROWS = 100_000


def bounded_path(root: Path, value: str) -> Path:
    result = (root / value).resolve()
    if not result.is_relative_to(root.resolve()):
        raise ValueError("Data and status paths must stay inside the configuration directory")
    return result


def load_config(path: str | Path) -> tuple[Path, list[Pipeline]]:
    path = Path(path).resolve()
    if path.stat().st_size > 256_000:
        raise ValueError("Configuration exceeds 256 KB")
    config = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or config.get("version") != 1:
        raise ValueError("Configuration version must be 1")
    raw = config.get("pipelines")
    if not isinstance(raw, list) or not 1 <= len(raw) <= 50:
        raise ValueError("Provide between 1 and 50 pipelines")
    pipelines = []
    names = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("Each pipeline must be an object")
        name = item.get("name", "")
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", name) or name in names:
            raise ValueError("Pipeline names must be unique lowercase identifiers")
        names.add(name)
        schema = item.get("schema")
        if not isinstance(schema, dict) or not schema or len(schema) > 100:
            raise ValueError(f"{name}: schema must contain 1–100 columns")
        if any(not isinstance(k, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", k) or not isinstance(v, str) or v not in {"string", "integer", "number", "timestamp", "boolean"} for k, v in schema.items()):
            raise ValueError(f"{name}: unsupported column name or type")
        for field in ("path", "run_status_path"):
            val = item.get(field)
            if field == "path" and not isinstance(val, str):
                raise ValueError(f"{name}: path is required")
            if val is not None:
                if not isinstance(val, str):
                    raise ValueError(f"{name}: invalid {field}")
                bounded_path(path.parent, val)
        keys = item.get("key_columns", [])
        deps = item.get("dependencies", [])
        if not isinstance(keys, list) or not all(isinstance(k, str) and k in schema for k in keys):
            raise ValueError(f"{name}: key_columns must reference the schema")
        if not isinstance(deps, list) or not all(isinstance(d, str) for d in deps) or len(deps) != len(set(deps)):
            raise ValueError(f"{name}: dependencies must be unique names")
        ts = item.get("timestamp_column")
        if not isinstance(ts, str) or ts not in schema or schema[ts] != "timestamp":
            raise ValueError(f"{name}: timestamp_column must have type timestamp")
        for field, default in (("max_age_minutes", 90), ("max_null_rate", .02), ("max_duplicate_rate", 0)):
            val = item.get(field, default)
            if type(val) not in {int, float} or not math.isfinite(val) or val < 0 or (field != "max_age_minutes" and val > 1):
                raise ValueError(f"{name}: invalid {field}")
        if type(item.get("allow_extra_columns", False)) is not bool:
            raise ValueError(f"{name}: allow_extra_columns must be a boolean")
        pipelines.append(Pipeline(name=name, path=item["path"], schema=schema, timestamp_column=ts,
            key_columns=tuple(keys), dependencies=tuple(deps), max_age_minutes=item.get("max_age_minutes", 90),
            max_null_rate=item.get("max_null_rate", .02), max_duplicate_rate=item.get("max_duplicate_rate", 0),
            allow_extra_columns=item.get("allow_extra_columns", False), run_status_path=item.get("run_status_path")))
    by_name = {p.name: p for p in pipelines}
    visited, active, ordered = set(), set(), []
    def visit(name: str) -> None:
        if name not in by_name:
            raise ValueError(f"Unknown dependency: {name}")
        if name in active:
            raise ValueError("Pipeline dependencies must form a DAG")
        if name in visited:
            return
        active.add(name)
        for dep in by_name[name].dependencies:
            visit(dep)
        active.remove(name)
        visited.add(name)
        ordered.append(by_name[name])
    for name in by_name:
        visit(name)
    return path.parent, ordered
