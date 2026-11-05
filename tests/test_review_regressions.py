import csv
import io
import json
import tempfile
import time
import unittest
from pathlib import Path

from pipeline_watchdog.collector import collect
from pipeline_watchdog.config import load_config
from pipeline_watchdog.demo import create_demo, set_scenario
from pipeline_watchdog.models import Pipeline, utcnow
from pipeline_watchdog.service import Watchdog
from pipeline_watchdog.triage import investigate


class ReviewRegressions(unittest.TestCase):
    def test_unhashable_status_is_reported_not_raised(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "demo"
            create_demo(root, "healthy")
            base, pipelines = load_config(root / "watchdog.json")
            for status in ([], {}, None, 0):
                with self.subTest(status=status):
                    (root / "data/orders_raw.status.json").write_text(json.dumps({"status": status}))
                    self.assertEqual(collect(base, pipelines[0], utcnow()).error, "invalid_run_status")
                    result = Watchdog(root / "watchdog.json", root / "watchdog.db").scan()
                    self.assertEqual(result["pipeline_count"], 3)

    def test_predictable_temp_symlink_cannot_overwrite_external_file(self):
        with tempfile.TemporaryDirectory() as directory:
            outside = Path(directory) / "important.txt"
            outside.write_text("must survive")
            root = Path(directory) / "demo"
            create_demo(root)
            (root / "data/orders_raw.tmp").symlink_to(outside)
            set_scenario(root, "cascade")
            self.assertEqual(outside.read_text(), "must survive")

    def test_dense_dependency_graph_is_bounded(self):
        pipelines = [Pipeline(f"p{i}", "unused.csv", {"t": "timestamp"}, "t", (), dependencies=tuple(f"p{j}" for j in range(i))) for i in range(50)]
        incidents = [{"pipeline": p.name, "id": p.name, "status": "open", "runbook": "inspect-source"} for p in pipelines]
        start = time.monotonic()
        result = investigate(incidents, pipelines)
        self.assertEqual(len(result["root_candidates"]), 1)
        self.assertEqual(len(result["root_candidates"][0]["affected_pipelines"]), 50)
        self.assertLess(time.monotonic() - start, 2)

    def test_missing_key_does_not_resolve_duplicate_incident(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "demo"
            create_demo(root, "quality-regression")
            path = root / "data/orders_clean.csv"
            rows = list(csv.DictReader(io.StringIO(path.read_text())))
            fields = [c for c in rows[0] if c != "order_id"]
            with path.open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)
            app = Watchdog(root / "watchdog.json", root / "watchdog.db")
            app.scan()
            checks = {i["check"] for i in app.store.incidents("open") if i["pipeline"] == "orders_clean"}
            self.assertIn("schema", checks)
            self.assertIn("duplicates", checks)
            current = next(s for s in app.store.latest() if s["pipeline"] == "orders_clean")
            self.assertNotIn("duplicates", current["evaluated_checks"])
            self.assertFalse(current["healthy"])
            set_scenario(root, "healthy")
            self.assertFalse(app.store.incidents("open"))

    def test_candidate_impacts_follow_topological_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "demo"
            create_demo(root)
            app = Watchdog(root / "watchdog.json", root / "watchdog.db")
            self.assertEqual(app.summary()["triage"]["root_candidates"][0]["affected_pipelines"], ["orders_raw", "orders_clean", "revenue_daily"])
