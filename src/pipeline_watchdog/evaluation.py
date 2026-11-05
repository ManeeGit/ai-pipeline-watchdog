"""Reproducible offline evaluation. This tests rule detection, not model intelligence."""
from __future__ import annotations

import tempfile
from pathlib import Path

from .demo import create_demo, set_scenario
from .service import Watchdog

EXPECTED = {
    "healthy": set(),
    "late-arrival": {"orders_raw:freshness", "orders_clean:freshness", "revenue_daily:freshness"},
    "schema-drift": {"orders_raw:schema"},
    "quality-regression": {"orders_clean:null_rate", "orders_clean:duplicates"},
    "volume-drop": {"orders_raw:volume", "orders_clean:volume"},
    "run-failure": {"revenue_daily:run_failure"},
    "cascade": {"orders_raw:schema", "orders_raw:freshness", "orders_raw:volume", "orders_clean:freshness", "orders_clean:null_rate", "orders_clean:duplicates", "orders_clean:volume", "revenue_daily:freshness", "revenue_daily:run_failure"},
}


def evaluate() -> dict:
    cases = []
    true_positive = false_positive = false_negative = 0
    with tempfile.TemporaryDirectory(prefix="watchdog-eval-") as directory:
        for scenario, expected in EXPECTED.items():
            root = Path(directory) / scenario
            create_demo(root, scenario)
            app = Watchdog(root / "watchdog.json", root / "watchdog.db")
            observed = {i["fingerprint"] for i in app.store.incidents("open")}
            true_positive += len(observed & expected)
            false_positive += len(observed - expected)
            false_negative += len(expected - observed)
            cases.append({"scenario": scenario, "expected": sorted(expected), "observed": sorted(observed), "passed": observed == expected})
        root = Path(directory) / "cascade"
        app = Watchdog(root / "watchdog.json", root / "watchdog.db")
        before = {i["id"] for i in app.store.incidents("open")}
        set_scenario(root, "healthy")
        cases.append({"scenario": "recovery", "passed": not app.store.incidents("open") and len(app.store.incidents("resolved")) == len(before)})
        set_scenario(root, "cascade")
        after = {i["id"] for i in app.store.incidents("open")}
        cases.append({"scenario": "reopen-without-duplication", "passed": before == after and any(e["event"] == "reopened" for e in app.store.stats()["events"])})
    return {"evaluation": "deterministic synthetic contract fixtures", "passed": all(c["passed"] for c in cases),
            "cases_passed": sum(c["passed"] for c in cases), "cases_total": len(cases),
            "precision": true_positive / max(true_positive + false_positive, 1),
            "recall": true_positive / max(true_positive + false_negative, 1),
            "true_positive_checks": true_positive, "false_positive_checks": false_positive, "false_negative_checks": false_negative,
            "scope": "Synthetic fixtures exercise implemented rules and lifecycle; not a production benchmark or LLM evaluation.", "cases": cases}
