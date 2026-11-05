from __future__ import annotations

import contextlib
import http.client
import io
import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from pipeline_watchdog.ai import explain_with_ollama, model_evidence, validate_response
from pipeline_watchdog.checks import detect
from pipeline_watchdog.cli import main
from pipeline_watchdog.collector import collect, valid_type
from pipeline_watchdog.config import load_config
from pipeline_watchdog.demo import configuration, create_demo, materialize, set_scenario
from pipeline_watchdog.evaluation import evaluate
from pipeline_watchdog.models import Finding, Pipeline, Snapshot, parse_time, stamp
from pipeline_watchdog.service import Watchdog
from pipeline_watchdog.store import Store
from pipeline_watchdog.triage import investigate
from pipeline_watchdog.web import make_server

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


class Workspace(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "data").mkdir()
        self.config = self.root / "watchdog.json"
        self.config.write_text(json.dumps(configuration()))
        materialize(self.root, "healthy", NOW)
        self.base, self.pipelines = load_config(self.config)

    def tearDown(self):
        self.temp.cleanup()

    def app(self):
        return Watchdog(self.config, self.root / "watchdog.db")

    def change_config(self, transform):
        data = configuration()
        transform(data)
        self.config.write_text(json.dumps(data))


class ConfigTests(Workspace):
    def test_dependency_order(self):
        self.assertEqual([p.name for p in self.pipelines], ["orders_raw", "orders_clean", "revenue_daily"])

    def test_reject_cycle(self):
        self.change_config(lambda c: c["pipelines"][0].update(dependencies=["revenue_daily"]))
        with self.assertRaisesRegex(ValueError, "DAG"):
            load_config(self.config)

    def test_reject_missing_dependency(self):
        self.change_config(lambda c: c["pipelines"][0].update(dependencies=["missing"]))
        with self.assertRaisesRegex(ValueError, "Unknown"):
            load_config(self.config)

    def test_reject_path_traversal(self):
        self.change_config(lambda c: c["pipelines"][0].update(path="../outside.csv"))
        with self.assertRaisesRegex(ValueError, "inside"):
            load_config(self.config)

    def test_reject_symlink_escape(self):
        outside = self.root.parent / "not-read.csv"
        (self.root / "escape").symlink_to(outside)
        self.change_config(lambda c: c["pipelines"][0].update(path="escape"))
        with self.assertRaises(ValueError):
            load_config(self.config)

    def test_reject_bad_thresholds(self):
        for value in (-1, 2, float("nan"), "0.1", True):
            with self.subTest(value=value):
                self.change_config(lambda c: c["pipelines"][0].update(max_null_rate=value))
                with self.assertRaises(ValueError):
                    load_config(self.config)

    def test_reject_duplicate_name(self):
        self.change_config(lambda c: c["pipelines"][1].update(name="orders_raw"))
        with self.assertRaises(ValueError):
            load_config(self.config)

    def test_reject_invalid_types(self):
        for value in ([], 99, None):
            self.change_config(lambda c: c["pipelines"][0].update(timestamp_column=value))
            with self.assertRaises(ValueError):
                load_config(self.config)

    def test_reject_invalid_schema_type(self):
        self.change_config(lambda c: c["pipelines"][0]["schema"].update(amount=[]))
        with self.assertRaises(ValueError):
            load_config(self.config)


class CollectorTests(Workspace):
    def test_valid_collection_and_no_raw_values(self):
        snapshot = collect(self.base, self.pipelines[0], NOW)
        self.assertIsNone(snapshot.error)
        self.assertGreater(snapshot.row_count, 190)
        self.assertEqual(snapshot.run_status, "success")
        self.assertNotIn("synthetic-", json.dumps(snapshot.to_dict()))

    def test_missing_source_does_not_crash(self):
        (self.root / "data/orders_raw.csv").unlink()
        self.assertEqual(collect(self.base, self.pipelines[0], NOW).error, "source_missing")

    def test_duplicate_headers_are_rejected(self):
        (self.root / "data/orders_raw.csv").write_text("a,a\n1,2\n")
        self.assertEqual(collect(self.base, self.pipelines[0], NOW).error, "invalid_csv_header")

    def test_ragged_csv_rejected(self):
        (self.root / "data/orders_raw.csv").write_text("a,b\n1,2,3\n")
        self.assertEqual(collect(self.base, self.pipelines[0], NOW).error, "malformed_csv_row")

    def test_malformed_quoted_csv_rejected(self):
        (self.root / "data/orders_raw.csv").write_text('a,b\n"unterminated,2\n')
        self.assertEqual(collect(self.base, self.pipelines[0], NOW).error, "source_parse_error")

    def test_invalid_status_is_bounded(self):
        (self.root / "data/orders_raw.status.json").write_text('["failed"]')
        self.assertEqual(collect(self.base, self.pipelines[0], NOW).error, "invalid_run_status")

    def test_byte_limit(self):
        with patch("pipeline_watchdog.collector.MAX_BYTES", 10):
            self.assertEqual(collect(self.base, self.pipelines[0], NOW).error, "source_too_large")

    def test_row_limit(self):
        with patch("pipeline_watchdog.collector.MAX_ROWS", 10):
            self.assertEqual(collect(self.base, self.pipelines[0], NOW).error, "row_limit_exceeded")

    def test_type_validation_and_timezone(self):
        self.assertFalse(valid_type("NaN", "number"))
        self.assertFalse(valid_type("inf", "number"))
        self.assertFalse(valid_type("1.5", "integer"))
        self.assertFalse(valid_type("yes", "boolean"))
        self.assertFalse(valid_type("2026-11-01T12:00:00", "timestamp"))
        self.assertTrue(valid_type("true", "boolean"))
        self.assertEqual(parse_time("2026-11-01T13:00:00+01:00"), NOW)


class DetectionTests(Workspace):
    def test_healthy_has_no_findings(self):
        self.assertEqual(detect(self.pipelines[0], collect(self.base, self.pipelines[0], NOW), [200] * 8), [])

    def test_empty_file_detected(self):
        (self.root / "data/orders_raw.csv").write_text("order_id,customer_id,region,amount,event_time\n")
        checks = {f.check for f in detect(self.pipelines[0], collect(self.base, self.pipelines[0], NOW), [])}
        self.assertEqual(checks, {"empty", "freshness"})

    def test_freshness_threshold_boundary(self):
        snapshot = collect(self.base, self.pipelines[0], NOW)
        snapshot.freshness_minutes = 60
        self.assertNotIn("freshness", [f.check for f in detect(self.pipelines[0], snapshot, [])])
        snapshot.freshness_minutes = 60.01
        self.assertIn("freshness", [f.check for f in detect(self.pipelines[0], snapshot, [])])

    def test_future_watermark(self):
        snapshot = collect(self.base, self.pipelines[0], NOW)
        snapshot.freshness_minutes = -6
        self.assertIn("clock_skew", [f.check for f in detect(self.pipelines[0], snapshot, [])])

    def test_warmup_does_not_guess_volume(self):
        snapshot = collect(self.base, self.pipelines[0], NOW)
        snapshot.row_count = 4
        self.assertNotIn("volume", [f.check for f in detect(self.pipelines[0], snapshot, [200] * 4)])
        self.assertIn("volume", [f.check for f in detect(self.pipelines[0], snapshot, [200] * 5)])

    def test_healthy_baseline_only(self):
        app = self.app()
        app.scan(NOW)
        self.assertEqual(len(app.store.baseline("orders_raw")), 1)
        materialize(self.root, "schema-drift", NOW)
        app.scan(NOW)
        self.assertEqual(len(app.store.baseline("orders_raw")), 1)

    def test_extra_columns_can_be_allowed(self):
        p = Pipeline("test", "unused", {"t": "timestamp"}, "t", (), allow_extra_columns=True)
        s = Snapshot("test", stamp(NOW), row_count=1, columns=["t", "extra"], freshness_minutes=1)
        self.assertEqual(detect(p, s, []), [])


class LifecycleTests(Workspace):
    def test_open_deduplicate_resolve_reopen(self):
        app = self.app()
        materialize(self.root, "run-failure", NOW)
        app.scan(NOW)
        first = app.store.incidents("open")[0]
        app.scan(NOW + timedelta(seconds=5))
        self.assertEqual(len(app.store.incidents("open")), 1)
        self.assertEqual(app.store.incidents("open")[0]["occurrences"], 2)
        self.assertEqual(len(app.store.stats()["events"]), 1)
        materialize(self.root, "healthy", NOW)
        app.scan(NOW + timedelta(seconds=10))
        self.assertEqual(app.store.incidents("open"), [])
        materialize(self.root, "run-failure", NOW)
        app.scan(NOW + timedelta(seconds=15))
        self.assertEqual(app.store.incidents("open")[0]["id"], first["id"])
        self.assertEqual([e["event"] for e in app.store.stats()["events"]], ["reopened", "resolved", "opened"])

    def test_failed_collection_does_not_claim_recovery(self):
        app = self.app()
        materialize(self.root, "run-failure", NOW)
        app.scan(NOW)
        (self.root / "data/revenue_daily.csv").unlink()
        app.scan(NOW)
        self.assertEqual({i["check"] for i in app.store.incidents("open")}, {"run_failure", "availability"})

    def test_schema_version_checked(self):
        store = Store(self.root / "future.db")
        with store.connect() as db:
            db.execute("UPDATE metadata SET value='99'")
        with self.assertRaisesRegex(ValueError, "schema version"):
            Store(self.root / "future.db")

    def test_database_is_private(self):
        store = Store(self.root / "private.db")
        self.assertEqual(store.path.stat().st_mode & 0o777, 0o600)

    def test_scan_rolls_back_atomically(self):
        store = Store(self.root / "atomic.db")
        s = Snapshot("orders_raw", stamp(NOW))
        bad = Finding("orders_raw", "bad", "warning", "Bad", {"unsupported": object()}, "inspect-source")
        with self.assertRaises(TypeError):
            store.record([s], [bad], 1)
        self.assertEqual(store.stats()["scan_count"], 0)
        self.assertEqual(store.latest(), [])

    def test_triage_follows_dependencies(self):
        app = self.app()
        materialize(self.root, "cascade", NOW)
        app.scan(NOW)
        triage = app.summary()["triage"]
        self.assertEqual([x["candidate_pipeline"] for x in triage["root_candidates"]], ["orders_raw"])
        self.assertEqual(len(triage["root_candidates"][0]["affected_pipelines"]), 3)
        self.assertIn("not proof", triage["root_candidates"][0]["reason"])


class AITests(Workspace):
    def items(self):
        app = self.app()
        materialize(self.root, "cascade", NOW)
        app.scan(NOW)
        return app.store.incidents("open"), app.summary()["triage"]

    def valid(self, items):
        return {"summary": "Inspect the cited evidence.", "evidence_ids": [items[0]["id"]], "runbook_ids": [items[0]["runbook"]], "uncertainty": "Correlation does not prove causation."}

    def test_valid_response(self):
        items, _ = self.items()
        self.assertTrue(validate_response(self.valid(items), items)["advisory_only"])

    def test_hallucinated_evidence_rejected(self):
        items, _ = self.items()
        payload = self.valid(items)
        payload["evidence_ids"] = ["invented"]
        with self.assertRaises(ValueError):
            validate_response(payload, items)

    def test_unapproved_actions_rejected(self):
        items, _ = self.items()
        for key, val in (("runbook_ids", ["delete-database"]), ("command", "rm -rf /")):
            payload = self.valid(items)
            payload[key] = val
            with self.assertRaises(ValueError):
                validate_response(payload, items)

    def test_oversized_narrative_rejected(self):
        items, _ = self.items()
        payload = self.valid(items)
        payload["summary"] = "x" * 1201
        with self.assertRaises(ValueError):
            validate_response(payload, items)

    def test_evidence_is_minimized(self):
        items, _ = self.items()
        text = json.dumps(model_evidence(items))
        self.assertNotIn("customer_id", text)
        self.assertNotIn("gross_amount", text)
        self.assertNotIn("orders_raw", text)
        self.assertNotIn("path", text)

    def test_provider_failure_retains_fallback(self):
        items, fallback = self.items()
        with patch("urllib.request.OpenerDirector.open", side_effect=OSError("network unavailable")):
            result = explain_with_ollama(items, fallback)
        self.assertEqual(result["provider"], "deterministic")
        self.assertEqual(result["evidence_ids"], fallback["evidence_ids"])
        self.assertIn("fallback_reason", result)

    def test_timeout_validation(self):
        items, fallback = self.items()
        with self.assertRaises(ValueError):
            explain_with_ollama(items, fallback, timeout=121)


class HTTPTests(Workspace):
    def setUp(self):
        super().setUp()
        self.watchdog = self.app()
        self.watchdog.scan(NOW)
        self.server = make_server(self.watchdog, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        super().tearDown()

    def request(self, method, path, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        conn.request(method, path, headers=headers or {})
        response = conn.getresponse()
        status, body, response_headers = response.status, response.read(), dict(response.getheaders())
        conn.close()
        return status, body, response_headers

    def test_summary_and_security_headers(self):
        code, body, headers = self.request("GET", "/api/summary")
        self.assertEqual(code, 200)
        self.assertEqual(len(json.loads(body)["pipelines"]), 3)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_reject_dns_rebinding_host(self):
        code, _, _ = self.request("GET", "/api/summary", {"Host": "evil.example"})
        self.assertEqual(code, 403)

    def test_reject_mutation(self):
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            self.assertEqual(self.request(method, "/api/summary")[0], 405)

    def test_no_path_traversal(self):
        self.assertEqual(self.request("GET", "/../watchdog.json")[0], 404)

    def test_metrics_and_health(self):
        code, body, _ = self.request("GET", "/metrics")
        self.assertEqual(code, 200)
        self.assertIn(b"watchdog_open_incidents 0", body)
        self.assertEqual(json.loads(self.request("GET", "/healthz")[1])["scope"], "http-process-only")

    def test_static_assets(self):
        for path in ("/", "/styles.css", "/app.js"):
            self.assertEqual(self.request("GET", path)[0], 200)


class DemoTests(unittest.TestCase):
    def test_full_fixture_evaluation(self):
        self.assertTrue(evaluate()["passed"])

    def test_demo_never_overwrites_existing_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "important.txt").write_text("keep")
            with self.assertRaises(ValueError):
                create_demo(Path(tmp))
            self.assertEqual(Path(tmp, "important.txt").read_text(), "keep")

    def test_scenario_cannot_target_ordinary_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                set_scenario(Path(tmp), "cascade")

    def test_cli_demo_and_ci_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "demo"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["demo", "--workspace", str(root)]), 0)
                self.assertEqual(main(["scan", "--config", str(root / "watchdog.json"), "--fail-on-incident"]), 2)
                self.assertEqual(main(["scenario", "healthy", "--workspace", str(root)]), 0)
                self.assertEqual(main(["scan", "--config", str(root / "watchdog.json"), "--fail-on-incident"]), 0)


if __name__ == "__main__":
    unittest.main()
