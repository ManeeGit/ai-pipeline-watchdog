from __future__ import annotations

from functools import cache

from .models import Pipeline

RUNBOOKS = {
    "inspect-source": {"title": "Verify source availability", "steps": ["Check that the configured CSV and run-status files exist and are readable.", "Confirm the producer wrote a complete, valid UTF-8 CSV atomically.", "Restore the last known-good output only after checking its provenance."]},
    "inspect-run": {"title": "Investigate the failed run", "steps": ["Inspect the producer's own logs for the latest failing run.", "Check upstream dependencies and resource limits before retrying.", "Retry through the owning orchestrator after confirming idempotency."]},
    "review-contract": {"title": "Review the schema contract", "steps": ["Compare producer changes with the versioned consumer contract.", "Quarantine incompatible output and assess downstream impact.", "Approve a compatible migration or roll back the producer; do not silently relax the contract."]},
    "restore-freshness": {"title": "Restore data freshness", "steps": ["Check upstream delivery and scheduler health.", "Verify event-time timezone and ingestion lag.", "Plan an idempotent backfill and validate freshness before releasing consumers."]},
    "check-clock": {"title": "Validate event time", "steps": ["Inspect timestamp format and timezone at the producer.", "Compare producer and collector clocks using an approved time source.", "Correct the transformation and replay only the affected partition."]},
    "inspect-quality": {"title": "Inspect the quality regression", "steps": ["Compare null counts across upstream and downstream stages.", "Review join keys, new optional fields, and mapping changes.", "Quarantine affected partitions until the data owner approves a corrected output."]},
    "deduplicate-input": {"title": "Investigate duplicate delivery", "steps": ["Check retry and replay boundaries for overlapping batches.", "Verify that the declared key matches the business grain.", "Prepare an idempotent deduplication plan and review before writing any data."]},
    "inspect-volume": {"title": "Investigate the volume shift", "steps": ["Compare upstream delivery counts and downstream filters.", "Check whether seasonality or a planned backfill explains the shift.", "Validate completeness before retrying or changing thresholds."]},
}


def investigate(incidents: list[dict], pipelines: list[Pipeline]) -> dict:
    open_items = [i for i in incidents if i["status"] == "open"]
    graph = {p.name: p.dependencies for p in pipelines}
    @cache
    def ancestors(name: str) -> set[str]:
        result = set()
        for dep in graph.get(name, ()):
            result.add(dep)
            result.update(ancestors(dep))
        return result
    affected = {i["pipeline"] for i in open_items}
    order = {pipeline.name: index for index, pipeline in enumerate(pipelines)}
    roots = sorted((p for p in affected if not ancestors(p) & affected), key=lambda name: order.get(name, len(order)))
    groups = []
    for root in roots:
        impacted = sorted((p for p in affected if p == root or root in ancestors(p)), key=lambda name: order.get(name, len(order)))
        evidence = [i["id"] for i in open_items if i["pipeline"] in impacted]
        groups.append({"candidate_pipeline": root, "affected_pipelines": impacted,
                       "evidence_ids": evidence, "confidence": "medium" if len(impacted) > 1 else "low",
                       "reason": "Earliest affected stage in the declared dependency graph. Correlation is not proof of causation."})
    runbook_ids = list(dict.fromkeys(i["runbook"] for i in open_items))
    return {"provider": "deterministic", "summary": (f"{len(open_items)} open checks across {len(affected)} pipeline(s). " +
            ("Inspect upstream candidates before retrying downstream jobs." if groups else "All observed contracts are currently healthy.")),
            "root_candidates": groups, "evidence_ids": [i["id"] for i in open_items],
            "recommended_runbooks": [{"id": key, **RUNBOOKS[key]} for key in runbook_ids],
            "limitations": ["Dependency correlation is a hypothesis, not a verified root cause.",
                           "No commands are generated or executed; recovery requires human review.",
                           "The fallback uses deterministic rules, not a language model."]}
