"""Cloud Run adapter: private GCS objects, atomic generation-checked state, read-only WSGI.

No cloud call occurs on import. This module never provisions infrastructure.
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import os
import re
import tempfile
import threading
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .config import MAX_BYTES, bounded_path, load_config
from .demo import SCENARIOS, configuration, create_demo, materialize
from .models import utcnow
from .service import Watchdog
from .web import STATIC

MAX_STATE_BYTES = 64 * 1024 * 1024
MAX_BUNDLE_BYTES = MAX_STATE_BYTES + 1024 * 1024
MAX_STAGED_INPUT_BYTES = 128 * 1024 * 1024
LOG = logging.getLogger("watchdog.cloud")


@dataclass(frozen=True)
class VersionedObject:
    content: bytes
    generation: int


class GoogleObjectStore:
    """Uses attached service-account ADC; no credential files or key storage."""
    def __init__(self, bucket_name: str):
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,220}[a-z0-9]", bucket_name):
            raise ValueError("Invalid state bucket name")
        from google.cloud import storage
        from google.api_core.exceptions import NotFound
        self.not_found = NotFound
        self.bucket = storage.Client().bucket(bucket_name)

    def read(self, name: str, max_bytes: int) -> VersionedObject | None:
        blob = self.bucket.blob(name)
        try:
            blob.reload(timeout=30, retry=None)
        except self.not_found:
            return None
        if blob.size is None or blob.size > max_bytes:
            raise ValueError("Cloud object exceeds its configured size limit")
        generation = int(blob.generation)
        content = blob.download_as_bytes(if_generation_match=generation, timeout=30, retry=None, checksum="auto")
        if len(content) > max_bytes:
            raise ValueError("Downloaded cloud object exceeds its size limit")
        return VersionedObject(content, generation)

    def write(self, name: str, content: bytes, expected_generation: int) -> None:
        if len(content) > MAX_BUNDLE_BYTES:
            raise ValueError("State bundle exceeds the cloud size budget")
        # Zero means create only if absent. A stale writer receives HTTP 412 and must start over.
        self.bucket.blob(name).upload_from_string(content, content_type="application/zip",
            if_generation_match=expected_generation, timeout=30, retry=None, checksum="auto")


def restore_bundle(content: bytes, root: Path) -> dict:
    if len(content) > MAX_BUNDLE_BYTES:
        raise ValueError("State bundle exceeds its size budget")
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        expected = {"watchdog.json", "watchdog.db", "manifest.json"}
        names = archive.namelist()
        if len(names) != 3 or set(names) != expected:
            raise ValueError("Invalid state bundle members")
        limits = {"watchdog.json": 256_000, "watchdog.db": MAX_STATE_BYTES, "manifest.json": 4096}
        for name in names:
            info = archive.getinfo(name)
            if info.file_size > limits[name] or info.is_dir():
                raise ValueError("State bundle member exceeds its size limit")
        manifest = json.loads(archive.read("manifest.json"))
        if not isinstance(manifest, dict) or manifest.get("format_version") != 1 or manifest.get("input_mode") not in {"synthetic", "gcs"}:
            raise ValueError("Unsupported state manifest")
        database = archive.read("watchdog.db")
        if not database.startswith(b"SQLite format 3\x00"):
            raise ValueError("Invalid state database header")
        # Fixed filenames, no extractall, no attacker-controlled filesystem paths.
        (root / "watchdog.json").write_bytes(archive.read("watchdog.json"))
        (root / "watchdog.db").write_bytes(database)
        (root / "watchdog.db").chmod(0o600)
        load_config(root / "watchdog.json")
        return manifest


def create_bundle(app: Watchdog, root: Path, input_mode: str) -> bytes:
    backup = root / "export.db"
    app.store.backup(backup)
    try:
        if backup.stat().st_size > MAX_STATE_BYTES:
            raise ValueError("State database exceeds 64 MiB; stop and migrate rather than silently discard evidence")
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(root / "watchdog.json", "watchdog.json")
            archive.write(backup, "watchdog.db")
            archive.writestr("manifest.json", json.dumps({"format_version": 1, "input_mode": input_mode,
                                                       "application_version": "0.2.0", "exported_at": utcnow().isoformat()}))
        return output.getvalue()
    finally:
        backup.unlink(missing_ok=True)


def stage_inputs(storage, root: Path) -> None:
    _, pipelines = load_config(root / "watchdog.json")
    paths = {p.path for p in pipelines} | {p.run_status_path for p in pipelines if p.run_status_path}
    total = 0
    for path in sorted(paths):
        if Path(path).is_absolute() or ".." in Path(path).parts:
            raise ValueError("Cloud input paths must be relative and cannot traverse parents")
        target = bounded_path(root, path)
        if target.name in {"watchdog.db", "watchdog.json", "export.db"} or target == root:
            raise ValueError("Input path conflicts with reserved state files")
        obj = storage.read("inputs/" + path, MAX_BYTES)
        if obj is None:
            # A missing configured source is still a measured availability incident.
            continue
        total += len(obj.content)
        if total > MAX_STAGED_INPUT_BYTES:
            raise ValueError("Cloud inputs exceed the 128 MiB per-job staging budget")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(obj.content)


def run_scan(storage, state_object: str = "state/watchdog.bundle", input_mode: str = "synthetic",
             scenario: str = "healthy", retain_days: int = 30) -> dict:
    if input_mode not in {"synthetic", "gcs"} or scenario not in SCENARIOS:
        raise ValueError("Invalid cloud input mode or synthetic scenario")
    previous = storage.read(state_object, MAX_BUNDLE_BYTES)
    with tempfile.TemporaryDirectory(prefix="watchdog-job-") as directory:
        root = Path(directory)
        if previous:
            manifest = restore_bundle(previous.content, root)
            if manifest["input_mode"] != input_mode:
                raise ValueError("Input mode changed; use a new versioned state object")
        elif input_mode == "synthetic":
            create_demo(root, "healthy")
        if input_mode == "gcs":
            config = storage.read("inputs/watchdog.json", 256_000)
            if config is None:
                raise ValueError("GCS input contract is missing")
            path = root / "watchdog.json"
            if path.exists() and json.loads(path.read_bytes()) != json.loads(config.content):
                raise ValueError("Contract changed; review migration and use a new versioned state object")
            path.write_bytes(config.content)
            stage_inputs(storage, root)
        else:
            if json.loads((root / "watchdog.json").read_text()) != configuration():
                raise ValueError("Synthetic contract changed; use a new state object")
            (root / "data").mkdir(exist_ok=True)
            materialize(root, scenario, utcnow())
        app = Watchdog(root / "watchdog.json", root / "watchdog.db")
        result = app.scan()
        retention = app.store.prune(retain_days, apply=True)
        content = create_bundle(app, root, input_mode)
        # The only externally visible commit. Generation precondition prevents lost updates.
        storage.write(state_object, content, previous.generation if previous else 0)
        LOG.info(json.dumps({"event": "state_committed", "input_mode": input_mode,
                             "state_bytes": len(content), **result, "retained_days": retain_days}))
        return {**result, "input_mode": input_mode, "state_committed": True, "state_bytes": len(content), "retention": retention}


class CloudDashboard:
    """IAM must be enforced by Cloud Run. Never run this public-facing without that layer."""
    def __init__(self, storage, state_object="state/watchdog.bundle", cache_seconds=30, max_scan_age=3900):
        self.storage, self.state_object = storage, state_object
        self.cache_seconds, self.max_scan_age = cache_seconds, max_scan_age
        self.lock = threading.Lock()
        self.cached_at = 0.0
        self.summary_cache = self.metrics_cache = self.readiness_cache = None

    def refresh(self):
        with self.lock:
            if self.summary_cache is not None and time.monotonic() - self.cached_at < self.cache_seconds:
                return
            obj = self.storage.read(self.state_object, MAX_BUNDLE_BYTES)
            if obj is None:
                raise ValueError("No committed state")
            with tempfile.TemporaryDirectory(prefix="watchdog-reader-") as directory:
                root = Path(directory)
                manifest = restore_bundle(obj.content, root)
                app = Watchdog(root / "watchdog.json", root / "watchdog.db")
                summary = app.summary()
                summary["mode"] = "gcp / advisory-only"
                summary["deployment"] = {"input_mode": manifest["input_mode"], "state_generation": str(obj.generation), "auth_boundary": "Cloud Run IAM", "max_scan_age_seconds": self.max_scan_age}
                self.summary_cache = json.dumps(summary, allow_nan=False).encode()
                self.metrics_cache = app.metrics().encode()
                self.readiness_cache = app.readiness(self.max_scan_age)
                self.cached_at = time.monotonic()

    def __call__(self, environ, start_response):
        method, path = environ.get("REQUEST_METHOD"), urlsplit(environ.get("PATH_INFO", "/")).path
        code, kind, body = "200 OK", "application/json", b""
        if method != "GET":
            code, body = "405 Method Not Allowed", b'{"error":"read_only_service"}'
        elif path == "/healthz":
            body = b'{"status":"ok","scope":"http-process-only"}'
        elif path in {"/", "/app.js", "/styles.css"}:
            name = "index.html" if path == "/" else path[1:]
            kind = {"index.html": "text/html", "app.js": "application/javascript", "styles.css": "text/css"}[name]
            body = (STATIC / name).read_bytes()
        elif path in {"/api/summary", "/metrics", "/readyz"}:
            try:
                self.refresh()
                if path == "/api/summary":
                    body = self.summary_cache
                elif path == "/metrics":
                    body, kind = self.metrics_cache, "text/plain; version=0.0.4"
                else:
                    body = json.dumps(self.readiness_cache).encode()
                    if not self.readiness_cache["ready"]:
                        code = "503 Service Unavailable"
            except Exception:
                LOG.error(json.dumps({"event": "dashboard_state_unavailable"}))
                code, body = "503 Service Unavailable", b'{"error":"committed_state_unavailable"}'
        else:
            code, body = "404 Not Found", b'{"error":"not_found"}'
        headers = [("Content-Type", kind + "; charset=utf-8"), ("Content-Length", str(len(body))),
                   ("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff"),
                   ("X-Frame-Options", "DENY"), ("Referrer-Policy", "no-referrer"),
                   ("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")]
        start_response(code, headers)
        return [body]


def create_app():
    if not os.environ.get("K_SERVICE"):
        raise RuntimeError("Cloud dashboard requires the documented IAM-protected Cloud Run deployment")
    return CloudDashboard(GoogleObjectStore(os.environ["WATCHDOG_BUCKET"]),
        os.environ.get("WATCHDOG_STATE_OBJECT", "state/watchdog.bundle"),
        max_scan_age=int(os.environ.get("WATCHDOG_MAX_SCAN_AGE_SECONDS", "3900")))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Cloud Run scanner. Does not provision resources.")
    parser.add_argument("command", choices=["scan"])
    parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        result = run_scan(GoogleObjectStore(os.environ["WATCHDOG_BUCKET"]),
                          os.environ.get("WATCHDOG_STATE_OBJECT", "state/watchdog.bundle"),
                          os.environ.get("WATCHDOG_INPUT_MODE", "synthetic"),
                          os.environ.get("WATCHDOG_SCENARIO", "healthy"),
                          int(os.environ.get("WATCHDOG_RETENTION_DAYS", "30")))
        print(json.dumps(result))
        return 0
    except Exception as exc:
        # Do not print SDK exceptions: they can contain URLs, data identifiers, or headers.
        LOG.error(json.dumps({"event": "cloud_scan_failed", "exception_type": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
