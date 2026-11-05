import io
import json
import tempfile
import unittest
import zipfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from pipeline_watchdog.cloud import (CloudDashboard, MAX_BUNDLE_BYTES, VersionedObject,
                                     restore_bundle, run_scan)
from pipeline_watchdog.demo import create_demo
from pipeline_watchdog.models import utcnow
from pipeline_watchdog.service import Watchdog
from pipeline_watchdog.store import Store


class GenerationConflict(Exception):
    pass


class FakeObjects:
    def __init__(self):
        self.objects = {}
        self.writes = 0
        self.reject_write = False
        self.reject_read = False

    def read(self, name, max_bytes):
        if self.reject_read:
            raise OSError("storage unavailable")
        obj = self.objects.get(name)
        if obj and len(obj.content) > max_bytes:
            raise ValueError("object too large")
        return obj

    def write(self, name, content, expected_generation):
        current = self.objects.get(name)
        if self.reject_write or (current.generation if current else 0) != expected_generation:
            raise GenerationConflict("precondition failed")
        self.objects[name] = VersionedObject(content, expected_generation + 1)
        self.writes += 1


def request(app, path, method="GET"):
    response = {}
    def start(status, headers):
        response.update(status=status, headers=dict(headers))
    body = b"".join(app({"REQUEST_METHOD": method, "PATH_INFO": path}, start))
    return response, body


class OperationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "demo"
        create_demo(self.root, "healthy")
        self.app = Watchdog(self.root / "watchdog.json", self.root / "watchdog.db")

    def tearDown(self):
        self.temp.cleanup()

    def test_identical_poll_does_not_inflate_baseline(self):
        before = self.app.store.baseline("orders_raw")
        for _ in range(6):
            self.app.scan()
        self.assertEqual(len(before), len(self.app.store.baseline("orders_raw")))

    def test_persisted_failure_and_recovery(self):
        with patch("pipeline_watchdog.service.collect", side_effect=OSError("secret source failure")):
            with self.assertRaises(OSError):
                self.app.scan()
        restarted = Watchdog(self.root / "watchdog.json", self.root / "watchdog.db")
        self.assertEqual(restarted.readiness()["reason"], "scan_failed")
        self.assertEqual(restarted.store.runtime()["failures_total"], 1)
        self.assertNotIn("secret", json.dumps(restarted.store.runtime()))
        restarted.scan()
        self.assertTrue(restarted.readiness()["ready"])
        self.assertEqual(restarted.store.runtime()["failures_total"], 1)
        self.assertEqual(restarted.store.runtime()["consecutive_failures"], 0)

    def test_readiness_detects_stale_monitor(self):
        self.assertTrue(self.app.readiness()["ready"])
        stale = self.app.readiness(now=utcnow() + timedelta(hours=1))
        self.assertFalse(stale["ready"])
        self.assertEqual(stale["reason"], "scan_stale")

    def test_backup_restores_evidence_and_refuses_overwrite(self):
        output = self.root / "backup.db"
        result = self.app.store.backup(output)
        self.assertEqual(result["integrity_check"], "ok")
        self.assertEqual(Store(output).stats(), self.app.store.stats())
        with self.assertRaises(ValueError):
            self.app.store.backup(output)

    def test_retention_preserves_incident_references_and_monotonic_counter(self):
        before = self.app.store.stats()
        total = self.app.store.runtime()["completed_total"]
        future = utcnow() + timedelta(days=60)
        plan = self.app.store.prune(30, now=future)
        self.assertGreater(plan["eligible_snapshots"], 0)
        self.assertEqual(self.app.store.stats(), before)
        result = self.app.store.prune(30, apply=True, now=future)
        self.assertTrue(result["applied"])
        self.assertEqual(len(self.app.store.latest()), 3)
        self.assertEqual(self.app.store.runtime()["completed_total"], total)
        with self.app.store.connect() as db:
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_unknown_schema_version_not_modified(self):
        with self.app.store.connect() as db:
            db.execute("UPDATE metadata SET value='99' WHERE key='schema_version'")
        with self.assertRaises(ValueError):
            Store(self.root / "watchdog.db")
        with self.app.store.connect() as db:
            self.assertEqual(db.execute("SELECT value FROM metadata").fetchone()[0], "99")


class CloudTests(unittest.TestCase):
    def test_synthetic_job_commits_atomically_and_retains_history(self):
        objects = FakeObjects()
        first = run_scan(objects, scenario="cascade")
        second = run_scan(objects, scenario="healthy")
        self.assertTrue(first["state_committed"])
        self.assertEqual(first["open_incidents"], 9)
        self.assertEqual(second["open_incidents"], 0)
        self.assertEqual(second["scan_id"], first["scan_id"] + 1)
        self.assertEqual(objects.writes, 2)

    def test_stale_writer_cannot_replace_committed_state(self):
        objects = FakeObjects()
        run_scan(objects)
        before = objects.objects["state/watchdog.bundle"]
        objects.reject_write = True
        with self.assertRaises(GenerationConflict):
            run_scan(objects, scenario="cascade")
        self.assertEqual(objects.objects["state/watchdog.bundle"], before)

    def test_reader_never_writes_and_exposes_readiness(self):
        objects = FakeObjects()
        run_scan(objects)
        writes = objects.writes
        app = CloudDashboard(objects)
        response, body = request(app, "/api/summary")
        self.assertEqual(response["status"], "200 OK")
        self.assertEqual(json.loads(body)["deployment"]["input_mode"], "synthetic")
        self.assertEqual(request(app, "/readyz")[0]["status"], "200 OK")
        self.assertEqual(objects.writes, writes)

    def test_cloud_methods_and_security_headers(self):
        app = CloudDashboard(FakeObjects())
        response, _ = request(app, "/", "POST")
        self.assertEqual(response["status"], "405 Method Not Allowed")
        self.assertIn("frame-ancestors 'none'", response["headers"]["Content-Security-Policy"])
        self.assertEqual(request(app, "/../watchdog.db")[0]["status"], "404 Not Found")
        self.assertEqual(request(app, "/healthz")[0]["status"], "200 OK")

    def test_missing_or_unavailable_state_is_not_ready(self):
        objects = FakeObjects()
        app = CloudDashboard(objects, cache_seconds=0)
        self.assertEqual(request(app, "/readyz")[0]["status"], "503 Service Unavailable")
        run_scan(objects)
        self.assertEqual(request(app, "/readyz")[0]["status"], "200 OK")
        objects.reject_read = True
        self.assertEqual(request(app, "/readyz")[0]["status"], "503 Service Unavailable")

    def test_bundle_excludes_raw_rows(self):
        objects = FakeObjects()
        run_scan(objects)
        bundle = objects.objects["state/watchdog.bundle"]
        with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
            self.assertEqual(set(archive.namelist()), {"watchdog.json", "watchdog.db", "manifest.json"})
            self.assertNotIn(b"synthetic-1001", archive.read("watchdog.db"))

    def test_invalid_bundle_names_and_size_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in ("../escape", "/tmp/escape"):
                output = io.BytesIO()
                with zipfile.ZipFile(output, "w") as archive:
                    archive.writestr(name, "bad")
                with self.assertRaises(ValueError):
                    restore_bundle(output.getvalue(), Path(directory))
            with patch("pipeline_watchdog.cloud.MAX_BUNDLE_BYTES", 1):
                with self.assertRaises(ValueError):
                    restore_bundle(b"abc", Path(directory))

    def test_input_mode_cannot_silently_change(self):
        objects = FakeObjects()
        run_scan(objects)
        with self.assertRaisesRegex(ValueError, "Input mode changed"):
            run_scan(objects, input_mode="gcs")

    def test_gcs_input_collection_and_contract_change_rejection(self):
        objects = FakeObjects()
        config = {"version": 1, "pipelines": [{"name": "events", "path": "events.csv", "schema": {"id": "integer", "time": "timestamp"}, "timestamp_column": "time", "key_columns": ["id"]}]}
        objects.objects["inputs/watchdog.json"] = VersionedObject(json.dumps(config).encode(), 1)
        objects.objects["inputs/events.csv"] = VersionedObject(f"id,time\n1,{utcnow().isoformat()}\n".encode(), 1)
        result = run_scan(objects, input_mode="gcs")
        self.assertEqual(result["open_incidents"], 0)
        config["pipelines"][0]["max_age_minutes"] = 15
        objects.objects["inputs/watchdog.json"] = VersionedObject(json.dumps(config).encode(), 2)
        with self.assertRaisesRegex(ValueError, "Contract changed"):
            run_scan(objects, input_mode="gcs")

    def test_reserved_input_path_rejected(self):
        objects = FakeObjects()
        config = {"version": 1, "pipelines": [{"name": "events", "path": "watchdog.db", "schema": {"time": "timestamp"}, "timestamp_column": "time", "key_columns": []}]}
        objects.objects["inputs/watchdog.json"] = VersionedObject(json.dumps(config).encode(), 1)
        with self.assertRaisesRegex(ValueError, "reserved"):
            run_scan(objects, input_mode="gcs")
        self.assertEqual(objects.writes, 0)

    def test_concurrent_scans_have_one_winner(self):
        import threading
        objects = FakeObjects()
        first = run_scan(objects)
        original_read = objects.read
        barrier = threading.Barrier(2)
        def synchronized_read(name, max_bytes):
            result = original_read(name, max_bytes)
            if name == "state/watchdog.bundle":
                barrier.wait(timeout=10)
            return result
        objects.read = synchronized_read
        outcomes = []
        def execute():
            try:
                outcomes.append(run_scan(objects))
            except GenerationConflict:
                outcomes.append("conflict")
        threads = [threading.Thread(target=execute) for _ in range(2)]
        for thread in threads:thread.start()
        for thread in threads:thread.join(timeout=15)
        self.assertFalse(any(t.is_alive() for t in threads))
        self.assertEqual(sum(value == "conflict" for value in outcomes), 1)
        self.assertEqual(len(outcomes), 2)
        winner = next(value for value in outcomes if isinstance(value, dict))
        self.assertEqual(winner["scan_id"], first["scan_id"] + 1)
        self.assertEqual(objects.writes, 2)
