from __future__ import annotations

import csv
import io
import json
import math
import time
from datetime import datetime
from pathlib import Path

from .config import MAX_BYTES, MAX_ROWS, bounded_path
from .models import Pipeline, Snapshot, parse_time, stamp


def valid_type(value: str, kind: str) -> bool:
    try:
        if kind == "integer":
            int(value)
        elif kind == "number":
            return math.isfinite(float(value))
        elif kind == "timestamp":
            parse_time(value)
        elif kind == "boolean":
            return value.lower() in {"true", "false", "0", "1"}
        return True
    except (ValueError, OverflowError):
        return False


def collect(root: Path, pipeline: Pipeline, now: datetime) -> Snapshot:
    started = time.monotonic()
    out = Snapshot(pipeline.name, stamp(now))
    try:
        if pipeline.run_status_path:
            status_path = bounded_path(root, pipeline.run_status_path)
            if status_path.stat().st_size > 16_384:
                raise ValueError("status_too_large")
            status = json.loads(status_path.read_text(encoding="utf-8"))
            if not isinstance(status, dict) or not isinstance(status.get("status"), str) or status.get("status") not in {"success", "failed", "running"}:
                raise ValueError("invalid_run_status")
            out.run_status = status["status"]
        source = bounded_path(root, pipeline.path)
        if not source.is_file():
            raise ValueError("source_missing")
        if source.stat().st_size > MAX_BYTES:
            raise ValueError("source_too_large")
        nulls, types, seen = {}, {}, set()
        duplicates = 0
        latest = None
        with source.open("rb") as binary:
            content = binary.read(MAX_BYTES + 1)
        if len(content) > MAX_BYTES:
            raise ValueError("source_too_large")
        with io.StringIO(content.decode("utf-8"), newline="") as stream:
            reader = csv.DictReader(stream, strict=True)
            columns = reader.fieldnames or []
            if not columns or len(columns) > 100 or len(set(columns)) != len(columns):
                raise ValueError("invalid_csv_header")
            if any(not col or len(col) > 128 for col in columns):
                raise ValueError("invalid_csv_header")
            out.columns = columns
            nulls = {column: 0 for column in pipeline.schema if column in columns}
            types = {column: 0 for column in nulls}
            for row in reader:
                out.row_count += 1
                if out.row_count > MAX_ROWS:
                    raise ValueError("row_limit_exceeded")
                if None in row or any(value is None for value in row.values()):
                    raise ValueError("malformed_csv_row")
                for column, kind in pipeline.schema.items():
                    if column not in columns:
                        continue
                    value = row[column].strip()
                    if not value:
                        nulls[column] += 1
                    elif not valid_type(value, kind):
                        types[column] += 1
                if pipeline.key_columns and all(c in columns for c in pipeline.key_columns):
                    key = tuple(row[c] for c in pipeline.key_columns)
                    if key in seen:
                        duplicates += 1
                    seen.add(key)
                raw_time = row.get(pipeline.timestamp_column, "").strip()
                if raw_time:
                    try:
                        parsed = parse_time(raw_time)
                        latest = max(latest, parsed) if latest else parsed
                    except (ValueError, OverflowError):
                        out.timestamp_errors += 1
        out.null_rates = {key: round(val / max(out.row_count, 1), 6) for key, val in nulls.items()}
        out.type_errors = {key: val for key, val in types.items() if val}
        out.duplicate_rate = round(duplicates / max(out.row_count, 1), 6)
        out.freshness_minutes = round((now - latest).total_seconds() / 60, 3) if latest else None
    except FileNotFoundError:
        out.error = "source_or_status_missing"
    except PermissionError:
        out.error = "source_unreadable"
    except (csv.Error, UnicodeError, json.JSONDecodeError):
        out.error = "source_parse_error"
    except ValueError as exc:
        known = {"status_too_large", "invalid_run_status", "source_missing", "source_too_large", "invalid_csv_header", "row_limit_exceeded", "malformed_csv_row"}
        out.error = str(exc) if str(exc) in known else "source_path_rejected"
    except OSError:
        out.error = "source_io_error"
    finally:
        out.duration_ms = round((time.monotonic() - started) * 1000, 3)
    return out
