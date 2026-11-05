from __future__ import annotations

from statistics import median

from .models import Finding, Pipeline, Snapshot


def detect(pipeline: Pipeline, snapshot: Snapshot, baseline: list[int]) -> list[Finding]:
    findings = []
    snapshot.evaluated_checks = ["availability"]
    def add(check, severity, title, evidence, runbook):
        findings.append(Finding(pipeline.name, check, severity, title, evidence, runbook))
    if snapshot.error:
        add("availability", "critical", "Source could not be inspected", {"error_code": snapshot.error}, "inspect-source")
        return findings
    snapshot.evaluated_checks.extend(["schema", "empty", "freshness"])
    if snapshot.run_status != "unknown":
        snapshot.evaluated_checks.append("run_failure")
    if set(pipeline.schema).issubset(snapshot.columns):
        snapshot.evaluated_checks.extend(["types", "null_rate"])
    if pipeline.key_columns and set(pipeline.key_columns).issubset(snapshot.columns):
        snapshot.evaluated_checks.append("duplicates")
    if snapshot.freshness_minutes is not None:
        snapshot.evaluated_checks.append("clock_skew")
    if pipeline.timestamp_column in snapshot.columns and snapshot.row_count:
        snapshot.evaluated_checks.append("timestamp_quality")
    if snapshot.run_status == "failed":
        add("run_failure", "critical", "Latest pipeline run failed", {"run_status": "failed"}, "inspect-run")
    missing = sorted(set(pipeline.schema) - set(snapshot.columns))
    extra = sorted(set(snapshot.columns) - set(pipeline.schema))
    if missing or (extra and not pipeline.allow_extra_columns):
        add("schema", "critical", "Schema contract changed", {"missing_columns": missing, "extra_columns": extra}, "review-contract")
    if snapshot.type_errors:
        add("types", "warning", "Values violate the column contract", {"invalid_values_by_column": snapshot.type_errors}, "review-contract")
    if snapshot.row_count == 0:
        add("empty", "critical", "Dataset contains no rows", {"row_count": 0}, "inspect-source")
    if snapshot.freshness_minutes is None:
        add("freshness", "critical", "No valid data watermark", {"freshness_minutes": None, "invalid_timestamps": snapshot.timestamp_errors}, "restore-freshness")
    elif snapshot.freshness_minutes < -5:
        add("clock_skew", "warning", "Data watermark is in the future", {"minutes_ahead": -snapshot.freshness_minutes}, "check-clock")
    elif snapshot.freshness_minutes > pipeline.max_age_minutes:
        add("freshness", "warning", "Data freshness target breached", {"freshness_minutes": snapshot.freshness_minutes, "threshold_minutes": pipeline.max_age_minutes}, "restore-freshness")
    if snapshot.timestamp_errors:
        add("timestamp_quality", "warning", "Some data timestamps cannot be parsed", {"invalid_timestamps": snapshot.timestamp_errors}, "check-clock")
    bad_nulls = {key: rate for key, rate in snapshot.null_rates.items() if rate > pipeline.max_null_rate}
    if bad_nulls:
        add("null_rate", "warning", "Null rate exceeds the quality budget", {"null_rates": bad_nulls, "threshold": pipeline.max_null_rate}, "inspect-quality")
    if snapshot.duplicate_rate > pipeline.max_duplicate_rate:
        add("duplicates", "warning", "Duplicate keys exceed the quality budget", {"duplicate_rate": snapshot.duplicate_rate, "threshold": pipeline.max_duplicate_rate}, "deduplicate-input")
    # Combine robust deviation with a material relative-change gate to avoid noisy low-volume alerts.
    if len(baseline) >= 5 and snapshot.row_count > 0:
        snapshot.evaluated_checks.append("volume")
        center = median(baseline)
        mad = median([abs(value - center) for value in baseline])
        scale = max(1.4826 * mad, center * .10, 1)
        score = abs(snapshot.row_count - center) / scale
        relative = abs(snapshot.row_count - center) / max(center, 1)
        if score >= 3.5 and relative >= .30:
            add("volume", "warning", "Row volume differs from its healthy baseline", {"row_count": snapshot.row_count, "baseline_median": center, "robust_score": round(score, 2), "relative_change": round(relative, 3), "baseline_samples": len(baseline)}, "inspect-volume")
    return findings
