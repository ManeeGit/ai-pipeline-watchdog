from __future__ import annotations

import csv
import json
import random
import tempfile
import os
from datetime import datetime, timedelta
from pathlib import Path

from .models import stamp, utcnow
from .service import Watchdog

SCENARIOS = ("healthy", "late-arrival", "schema-drift", "quality-regression", "volume-drop", "run-failure", "cascade")
MARKER = "synthetic-pipeline-watchdog-v1"


def configuration() -> dict:
    schema = {"order_id": "integer", "customer_id": "string", "region": "string", "amount": "number", "event_time": "timestamp"}
    return {"version": 1, "pipelines": [
        {"name": "orders_raw", "path": "data/orders_raw.csv", "schema": schema, "timestamp_column": "event_time", "key_columns": ["order_id"], "max_age_minutes": 60, "run_status_path": "data/orders_raw.status.json"},
        {"name": "orders_clean", "path": "data/orders_clean.csv", "schema": schema, "timestamp_column": "event_time", "key_columns": ["order_id"], "dependencies": ["orders_raw"], "max_age_minutes": 90, "run_status_path": "data/orders_clean.status.json"},
        {"name": "revenue_daily", "path": "data/revenue_daily.csv", "schema": {"region": "string", "revenue": "number", "orders": "integer", "event_time": "timestamp"}, "timestamp_column": "event_time", "key_columns": ["region"], "dependencies": ["orders_clean"], "max_age_minutes": 120, "run_status_path": "data/revenue_daily.status.json"}
    ]}


def write_csv(path: Path, rows: list[dict]) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".watchdog-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        Path(temporary).replace(path)
    finally:
        if Path(temporary).exists():
            Path(temporary).unlink()


def materialize(root: Path, scenario: str, now: datetime, seed: int = 42) -> None:
    if scenario not in SCENARIOS:
        raise ValueError("Unknown demo scenario")
    rng = random.Random(seed)
    count = 45 if scenario in {"volume-drop", "cascade"} else rng.randint(196, 208)
    lag = 240 if scenario in {"late-arrival", "cascade"} else 8
    rows = [{"order_id": i + 1, "customer_id": f"synthetic-{rng.randint(1000, 9999)}",
             "region": ["North", "South", "East", "West"][i % 4], "amount": round(rng.uniform(12, 350), 2),
             "event_time": stamp(now - timedelta(minutes=lag + rng.randint(0, 20)))} for i in range(count)]
    clean = [dict(row) for row in rows]
    if scenario in {"quality-regression", "cascade"}:
        for row in clean[:max(1, count // 4)]:
            row["customer_id"] = ""
        for i in range(max(1, count // 5)):
            clean[-i - 1]["order_id"] = clean[i]["order_id"]
    raw = [dict(row) for row in rows]
    if scenario in {"schema-drift", "cascade"}:
        for row in raw:
            row["gross_amount"] = row.pop("amount")
    totals = [{"region": region, "revenue": round(sum(r["amount"] for r in rows if r["region"] == region), 2),
               "orders": sum(r["region"] == region for r in rows),
               "event_time": stamp(now - timedelta(minutes=lag))} for region in ["North", "South", "East", "West"]]
    for name, data in (("orders_raw", raw), ("orders_clean", clean), ("revenue_daily", totals)):
        write_csv(root / "data" / f"{name}.csv", data)
        state = "failed" if name == "revenue_daily" and scenario in {"run-failure", "cascade"} else "success"
        (root / "data" / f"{name}.status.json").write_text(json.dumps({"status": state}), encoding="utf-8")


def create_demo(root: Path, scenario: str = "cascade", now: datetime | None = None) -> dict:
    root = root.resolve()
    if root.exists() and any(root.iterdir()):
        raise ValueError("Demo directory must be empty. Choose a new directory; existing work is never overwritten.")
    root.mkdir(parents=True, exist_ok=True)
    (root / "data").mkdir(exist_ok=True)
    (root / ".watchdog-demo.json").write_text(json.dumps({"marker": MARKER, "synthetic": True}), encoding="utf-8")
    (root / "watchdog.json").write_text(json.dumps(configuration(), indent=2) + "\n", encoding="utf-8")
    now = now or utcnow()
    app = Watchdog(root / "watchdog.json", root / "watchdog.db")
    for hour in range(12, 0, -1):
        at = now - timedelta(hours=hour)
        materialize(root, "healthy", at, seed=42 + hour)
        app.scan(at)
    materialize(root, scenario, now)
    result = app.scan(now)
    return {"workspace": str(root), "scenario": scenario, **result}


def set_scenario(root: Path, scenario: str) -> dict:
    root = root.resolve()
    marker = root / ".watchdog-demo.json"
    if not marker.is_file() or json.loads(marker.read_text(encoding="utf-8")).get("marker") != MARKER:
        raise ValueError("Scenario injection is restricted to a generated demo workspace")
    for name in ("orders_raw", "orders_clean", "revenue_daily"):
        for suffix in (".csv", ".status.json"):
            path = (root / "data" / (name + suffix)).resolve()
            if not path.is_relative_to(root) or (root / "data").is_symlink():
                raise ValueError("Demo data path is unsafe")
    now = utcnow()
    materialize(root, scenario, now)
    return Watchdog(root / "watchdog.json", root / "watchdog.db").scan(now)
