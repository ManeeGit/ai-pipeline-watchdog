from __future__ import annotations

import hashlib
from contextlib import contextmanager
import json
import os
import sqlite3
import tempfile
from datetime import timedelta
from pathlib import Path

from .models import Finding, Snapshot, stamp, utcnow


class Store:
    """One connection per operation, transactional scans, WAL readers, bounded history reads."""
    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='metadata'").fetchone()
            if exists:
                row = db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
                if row is None or row[0] not in {"1", "2"}:
                    raise ValueError("Unsupported database schema version")
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                INSERT OR IGNORE INTO metadata VALUES('schema_version', '2');
                CREATE TABLE IF NOT EXISTS scans(
                    id INTEGER PRIMARY KEY, observed_at TEXT NOT NULL, duration_ms REAL NOT NULL,
                    pipeline_count INTEGER NOT NULL, findings_count INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS snapshots(
                    id INTEGER PRIMARY KEY, scan_id INTEGER NOT NULL REFERENCES scans(id),
                    pipeline TEXT NOT NULL, observed_at TEXT NOT NULL, healthy INTEGER NOT NULL,
                    row_count INTEGER NOT NULL, payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS snapshots_pipeline ON snapshots(pipeline, id DESC);
                CREATE TABLE IF NOT EXISTS incidents(
                    id TEXT PRIMARY KEY, fingerprint TEXT UNIQUE NOT NULL, pipeline TEXT NOT NULL,
                    check_name TEXT NOT NULL, severity TEXT NOT NULL, status TEXT NOT NULL,
                    first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, resolved_at TEXT,
                    occurrences INTEGER NOT NULL, snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
                    payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS incident_events(
                    id INTEGER PRIMARY KEY, incident_id TEXT NOT NULL REFERENCES incidents(id),
                    event TEXT NOT NULL, observed_at TEXT NOT NULL, snapshot_id INTEGER NOT NULL REFERENCES snapshots(id));
                CREATE INDEX IF NOT EXISTS incident_events_recent ON incident_events(id DESC);
                CREATE TABLE IF NOT EXISTS baseline_samples(
                    pipeline TEXT NOT NULL, fingerprint TEXT NOT NULL, row_count INTEGER NOT NULL,
                    last_seen TEXT NOT NULL, PRIMARY KEY(pipeline, fingerprint));
                CREATE TABLE IF NOT EXISTS runtime_state(
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1), last_attempt_at TEXT,
                    last_completed_at TEXT, last_error_code TEXT, consecutive_failures INTEGER NOT NULL DEFAULT 0,
                    failures_total INTEGER NOT NULL DEFAULT 0, completed_total INTEGER NOT NULL DEFAULT 0);
                INSERT OR IGNORE INTO runtime_state(singleton) VALUES(1);
                UPDATE runtime_state SET last_completed_at=(SELECT MAX(observed_at) FROM scans)
                    WHERE last_completed_at IS NULL;
                UPDATE metadata SET value='2' WHERE key='schema_version';
            """)
            if "completed_total" not in {row[1] for row in db.execute("PRAGMA table_info(runtime_state)")}:
                db.execute("ALTER TABLE runtime_state ADD COLUMN completed_total INTEGER NOT NULL DEFAULT 0")
            db.execute("UPDATE runtime_state SET completed_total=MAX(completed_total,(SELECT COUNT(*) FROM scans))")
        os.chmod(self.path, 0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA trusted_schema=OFF")
        db.execute("PRAGMA busy_timeout=5000")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def baseline(self, pipeline: str) -> list[int]:
        with self.connect() as db:
            return [r[0] for r in db.execute("SELECT row_count FROM baseline_samples WHERE pipeline=? ORDER BY last_seen DESC LIMIT 30", (pipeline,))]

    def record(self, snapshots: list[Snapshot], findings: list[Finding], duration_ms: float) -> int:
        by_pipeline: dict[str, list[Finding]] = {}
        for finding in findings:
            by_pipeline.setdefault(finding.pipeline, []).append(finding)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            cursor = db.execute("INSERT INTO scans(observed_at,duration_ms,pipeline_count,findings_count) VALUES(?,?,?,?)",
                (snapshots[0].observed_at, duration_ms, len(snapshots), len(findings)))
            scan_id = cursor.lastrowid
            for snapshot in snapshots:
                current = by_pipeline.get(snapshot.pipeline, [])
                cursor = db.execute("INSERT INTO snapshots(scan_id,pipeline,observed_at,healthy,row_count,payload) VALUES(?,?,?,?,?,?)",
                    (scan_id, snapshot.pipeline, snapshot.observed_at, int(not current), snapshot.row_count, json.dumps(snapshot.to_dict())))
                snapshot.snapshot_id = cursor.lastrowid
                fingerprints = set()
                for finding in current:
                    fingerprint = finding.fingerprint
                    fingerprints.add(fingerprint)
                    incident_id = hashlib.sha256(fingerprint.encode()).hexdigest()[:16]
                    existing = db.execute("SELECT status FROM incidents WHERE fingerprint=?", (fingerprint,)).fetchone()
                    event = "opened" if existing is None else "reopened" if existing["status"] == "resolved" else None
                    db.execute("""INSERT INTO incidents VALUES(?,?,?,?,?,'open',?,?,NULL,1,?,?)
                        ON CONFLICT(fingerprint) DO UPDATE SET severity=excluded.severity,status='open',last_seen=excluded.last_seen,
                        resolved_at=NULL,occurrences=incidents.occurrences+1,snapshot_id=excluded.snapshot_id,payload=excluded.payload""",
                        (incident_id, fingerprint, finding.pipeline, finding.check, finding.severity, snapshot.observed_at,
                         snapshot.observed_at, snapshot.snapshot_id, json.dumps(finding.to_dict())))
                    if event:
                        db.execute("INSERT INTO incident_events(incident_id,event,observed_at,snapshot_id) VALUES(?,?,?,?)", (incident_id, event, snapshot.observed_at, snapshot.snapshot_id))
                # Failed collection cannot establish recovery of checks that were not evaluated.
                if not snapshot.error:
                    for incident in db.execute("SELECT id,fingerprint,check_name FROM incidents WHERE pipeline=? AND status='open'", (snapshot.pipeline,)).fetchall():
                        if incident["fingerprint"] not in fingerprints and incident["check_name"] in snapshot.evaluated_checks:
                            db.execute("UPDATE incidents SET status='resolved',resolved_at=? WHERE id=?", (snapshot.observed_at, incident["id"]))
                            db.execute("INSERT INTO incident_events(incident_id,event,observed_at,snapshot_id) VALUES(?,?,?,?)", (incident["id"], "resolved", snapshot.observed_at, snapshot.snapshot_id))
                if db.execute("SELECT 1 FROM incidents WHERE pipeline=? AND status='open' LIMIT 1", (snapshot.pipeline,)).fetchone():
                    db.execute("UPDATE snapshots SET healthy=0 WHERE id=?", (snapshot.snapshot_id,))
                elif not current and snapshot.source_fingerprint:
                    db.execute("""INSERT INTO baseline_samples VALUES(?,?,?,?) ON CONFLICT(pipeline,fingerprint)
                        DO UPDATE SET last_seen=excluded.last_seen""", (snapshot.pipeline, snapshot.source_fingerprint, snapshot.row_count, snapshot.observed_at))
                    db.execute("""DELETE FROM baseline_samples WHERE pipeline=? AND fingerprint NOT IN
                        (SELECT fingerprint FROM baseline_samples WHERE pipeline=? ORDER BY last_seen DESC LIMIT 30)""", (snapshot.pipeline, snapshot.pipeline))
            db.execute("UPDATE runtime_state SET last_completed_at=?,last_error_code=NULL,consecutive_failures=0,completed_total=completed_total+1 WHERE singleton=1", (snapshots[0].observed_at,))
            return int(scan_id)

    def incidents(self, status: str | None = None) -> list[dict]:
        with self.connect() as db:
            query = "SELECT * FROM incidents"
            args = ()
            if status:
                query += " WHERE status=?"
                args = (status,)
            query += " ORDER BY CASE status WHEN 'open' THEN 0 ELSE 1 END, CASE severity WHEN 'critical' THEN 0 ELSE 1 END, last_seen DESC"
            result = []
            for row in db.execute(query, args):
                data = dict(row)
                data.update(json.loads(data.pop("payload")))
                result.append(data)
            return result

    def latest(self) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT s.* FROM snapshots s JOIN (SELECT pipeline, MAX(id) id FROM snapshots GROUP BY pipeline) t ON s.id=t.id ORDER BY s.pipeline")
            result = []
            for row in rows:
                data = json.loads(row["payload"])
                data.update(snapshot_id=row["id"], healthy=bool(row["healthy"]))
                result.append(data)
            return result

    def history(self, pipeline: str, limit: int = 48) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT id,payload,healthy FROM snapshots WHERE pipeline=? ORDER BY id DESC LIMIT ?", (pipeline, min(max(limit, 1), 200)))
            return list(reversed([dict(json.loads(row["payload"]), snapshot_id=row["id"], healthy=bool(row["healthy"])) for row in rows]))

    def stats(self) -> dict:
        with self.connect() as db:
            last = db.execute("SELECT * FROM scans ORDER BY id DESC LIMIT 1").fetchone()
            return {"scan_count": db.execute("SELECT COUNT(*) FROM scans").fetchone()[0],
                    "snapshot_count": db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0],
                    "last_scan": dict(last) if last else None,
                    "events": [dict(row) for row in db.execute("SELECT * FROM incident_events ORDER BY id DESC LIMIT 30")]}


    def mark_attempt(self, observed_at: str) -> None:
        with self.connect() as db:
            db.execute("UPDATE runtime_state SET last_attempt_at=? WHERE singleton=1", (observed_at,))

    def mark_failure(self, code: str) -> None:
        allowed = {"collection_failed", "persistence_failed", "scan_failed"}
        with self.connect() as db:
            db.execute("UPDATE runtime_state SET last_error_code=?,consecutive_failures=consecutive_failures+1,failures_total=failures_total+1 WHERE singleton=1", (code if code in allowed else "scan_failed",))

    def runtime(self) -> dict:
        with self.connect() as db:
            return dict(db.execute("SELECT * FROM runtime_state WHERE singleton=1").fetchone())

    def backup(self, output: str | Path) -> dict:
        output = Path(output).absolute()
        if output.exists() or output.is_symlink():
            raise ValueError("Backup destination already exists; refusing to overwrite")
        descriptor, temporary = tempfile.mkstemp(prefix=".watchdog-backup-", dir=output.parent)
        os.close(descriptor)
        try:
            with self.connect() as source:
                target = sqlite3.connect(temporary)
                try:
                    source.backup(target)
                    if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise ValueError("Backup integrity verification failed")
                finally:
                    target.close()
            os.chmod(temporary, 0o600)
            os.link(temporary, output)  # Exclusive publication: a competing path never gets overwritten.
            return {"output": str(output), "bytes": output.stat().st_size, "integrity_check": "ok"}
        finally:
            Path(temporary).unlink(missing_ok=True)

    def prune(self, retain_days: int = 30, apply: bool = False, now=None) -> dict:
        if type(retain_days) is not int or retain_days < 1:
            raise ValueError("Retention must be a positive number of days")
        cutoff = stamp((now or utcnow()) - timedelta(days=retain_days))
        # Preserve current observations and every snapshot cited by incident evidence or lifecycle events.
        predicate = """observed_at < ? AND id NOT IN (SELECT snapshot_id FROM incidents)
            AND id NOT IN (SELECT snapshot_id FROM incident_events)
            AND id NOT IN (SELECT MAX(id) FROM snapshots GROUP BY pipeline)"""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            count = db.execute("SELECT COUNT(*) FROM snapshots WHERE " + predicate, (cutoff,)).fetchone()[0]
            if apply:
                db.execute("DELETE FROM snapshots WHERE " + predicate, (cutoff,))
                db.execute("DELETE FROM scans WHERE id NOT IN (SELECT scan_id FROM snapshots)")
            return {"cutoff": cutoff, "eligible_snapshots": count, "applied": apply,
                    "preserves": "latest observations and all incident/event evidence"}
