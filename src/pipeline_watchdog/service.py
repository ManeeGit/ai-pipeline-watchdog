from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path

from .checks import detect
from .collector import collect
from .config import load_config
from .models import utcnow, stamp, parse_time
from .store import Store
from .triage import investigate

LOG = logging.getLogger("watchdog")


class Watchdog:
    def __init__(self, config: str | Path, db: str | Path):
        self.root, self.pipelines = load_config(config)
        self.store = Store(db)
        self.last_internal_error = None

    def scan(self, now: datetime | None = None) -> dict:
        now = now or utcnow()
        started = time.monotonic()
        try:
            self.store.mark_attempt(stamp(now))
            snapshots, findings = [], []
            for pipeline in self.pipelines:
                snapshot = collect(self.root, pipeline, now)
                snapshots.append(snapshot)
                findings.extend(detect(pipeline, snapshot, self.store.baseline(pipeline.name)))
            duration = round((time.monotonic() - started) * 1000, 3)
            scan_id = self.store.record(snapshots, findings, duration)
            self.last_internal_error = None
            result = {"scan_id": scan_id, "pipeline_count": len(snapshots), "findings_count": len(findings),
                      "duration_ms": duration, "open_incidents": len(self.store.incidents("open"))}
            LOG.info(json.dumps({"event": "scan_completed", **result}))
            return result
        except Exception:
            self.last_internal_error = "scan_failed"
            try:
                self.store.mark_failure("scan_failed")
            except Exception:
                pass  # Broken persistence must not hide the original operational failure.
            LOG.error(json.dumps({"event": "scan_failed", "error_code": "scan_failed"}))
            raise

    def readiness(self, max_age_seconds: int = 180, now: datetime | None = None) -> dict:
        if max_age_seconds < 1:
            raise ValueError("Readiness age must be positive")
        runtime = self.store.runtime()
        completed = runtime["last_completed_at"]
        age = ((now or utcnow()) - parse_time(completed)).total_seconds() if completed else None
        reason = ("scan_failed" if self.last_internal_error or runtime["last_error_code"] else
                  "no_completed_scan" if age is None else "clock_skew" if age < -60 else
                  "scan_stale" if age > max_age_seconds else "ready")
        return {"ready": reason == "ready", "reason": reason, "last_completed_at": completed,
                "scan_age_seconds": age, "max_age_seconds": max_age_seconds,
                "consecutive_failures": runtime["consecutive_failures"],
                "scope": "scanner-operation; data contract health is separate"}

    def summary(self) -> dict:
        latest = self.store.latest()
        configured = {p.name for p in self.pipelines}
        latest = [s for s in latest if s["pipeline"] in configured]
        incidents = [i for i in self.store.incidents() if i["pipeline"] in configured]
        return {"version": "0.2.0", "mode": "local-first / advisory-only", "generated_at": utcnow().isoformat(),
                "pipelines": [{"name": p.name, "dependencies": list(p.dependencies), "max_age_minutes": p.max_age_minutes,
                               "snapshot": next((s for s in latest if s["pipeline"] == p.name), None),
                               "history": self.store.history(p.name, 24)} for p in self.pipelines],
                "incidents": incidents, "triage": investigate(incidents, self.pipelines), "stats": self.store.stats(), "runtime": self.store.runtime()}

    def metrics(self) -> str:
        summary = self.summary()
        lines = ["# HELP watchdog_open_incidents Current unresolved checks.", "# TYPE watchdog_open_incidents gauge",
                 f'watchdog_open_incidents {sum(i["status"] == "open" for i in summary["incidents"])}',
                 "# HELP watchdog_scans_total Persisted monitoring scans.", "# TYPE watchdog_scans_total counter",
                 f'watchdog_scans_total {summary["runtime"]["completed_total"]}',
                 f'watchdog_scan_failures_total {summary["runtime"]["failures_total"]}',
                 f'watchdog_consecutive_failures {summary["runtime"]["consecutive_failures"]}']
        last = summary["stats"]["last_scan"]
        if last:
            lines.append(f'watchdog_scan_duration_ms {last["duration_ms"]}')
        for pipeline in summary["pipelines"]:
            s = pipeline["snapshot"]
            if s:
                label = f'pipeline="{pipeline["name"]}"'
                lines.extend([f'watchdog_pipeline_healthy{{{label}}} {int(s["healthy"])}', f'watchdog_rows{{{label}}} {s["row_count"]}'])
                if s["freshness_minutes"] is not None:
                    lines.append(f'watchdog_freshness_minutes{{{label}}} {s["freshness_minutes"]}')
        return "\n".join(lines) + "\n"
