# Architecture and decisions

## The reliability boundary

The system separates **measurement**, **diagnosis**, and **action**. Only measurement and advisory diagnosis exist in this version. The collector reads designated local files. The detector applies explicit contracts. The model cannot change a contract, suppress an incident, execute a tool, or trigger a retry.

Each scan captures an observation timestamp, collects bounded CSV inputs in memory, computes aggregates, and evaluates all applicable checks. It records the whole scan in one SQLite transaction. A serialization or database error rolls back that scan instead of persisting half an incident graph.

## Modules

- `config.py`: versioned contract validation, safe paths, unique identifiers, DAG validation and topological ordering.
- `collector.py`: UTF-8 CSV inspection; bounded input bytes/rows/columns; aggregate quality and watermark calculation; redacted error categories.
- `checks.py`: freshness, clock, schema, empty output, data types, nulls, duplicates, volume, status. Records which checks were actually evaluated.
- `store.py`: schema version, transaction boundaries, WAL, private database permissions, history, deduplicated incident state and transitions.
- `triage.py`: memoized ancestor traversal and reviewable playbooks.
- `ai.py`: explicit local Ollama HTTP request, input minimization, bounded response, reference validation and fallback.
- `service.py`: scan orchestration, summaries, structured telemetry, Prometheus text.
- `web.py` / `static/`: read-only local presentation. No mutating route and no model endpoint.
- `demo.py` / `evaluation.py`: generated fixtures, expected labels, reproducible lifecycle validation.

## Data model

`runtime_state` persists operational failure/readiness counters. `baseline_samples` maintains at most thirty distinct healthy content fingerprints per pipeline. `scans` identifies an observation batch and records collection/detection latency. `snapshots` stores aggregate JSON plus indexed pipeline, time, row count, and health fields. `incidents` stores stable IDs keyed by `pipeline:check`, current evidence, first/last observation, count, resolution time, and source snapshot. `incident_events` records only opening, reopening, and resolution transitions, not every poll.

A repeated failed check increments its observation count without duplicating the incident. A passing check resolves an open incident only if its prerequisites were actually inspectable. For example, losing a key column cannot prove that duplicates disappeared. A collector failure leaves prior findings open and adds availability evidence. A later trustworthy healthy scan can resolve them.

Snapshots store no cell samples. Column names and aggregate evidence remain sensitive local metadata even though raw rows are omitted. Historical snapshots are immutable; current incidents reference their latest supporting snapshot. Resolved incidents retain the last failing evidence and a separate resolution event.

## Baseline reasoning

Use up to thirty distinct **healthy content fingerprints**. Require at least five before evaluating volume. Repeated unchanged-file polls update recency but do not add baseline weight. Let `m` be median row count and `MAD` the median absolute deviation. The scale is `max(1.4826 × MAD, 0.1 × m, 1)`. Alert only when deviation/scale ≥ 3.5 **and** relative deviation ≥ 0.30. A floor prevents constant small baselines from creating unstable scores.

This simple detector is inspectable and works without scientific packages. It does not model weekday effects, backfills, partitions, or unique producer execution IDs. Failed observations do not contaminate the healthy reference distribution. A lasting expected volume change requires an intentional baseline/configuration strategy outside this prototype.

## Why SQLite and standard-library HTTP?

A single-user local demonstration should not require three containers. SQLite provides transactions, persistence, WAL readers, and a useful inspection surface. Every connection is closed explicitly. The server is deliberately loopback-only and read-only, with Host validation, no CORS, no third-party assets, CSP and anti-framing headers. It is not an internet deployment architecture.

The dashboard polls persisted state independently of scanning. `serve --watch` adds one scanner thread. Each database operation creates its own connection. The scan latency metric excludes SQLite commit time; the standalone benchmark measures the complete scan call.

## AI decision

A local model can improve the readability of incident evidence without owning correctness-critical state. Its payload excludes free-form source strings, reducing both privacy and prompt-injection exposure. Structured citations and approved playbook IDs reduce unsupported actions, but do **not** prove the narrative is factually entailed. UI text is inserted with `textContent`; no model HTML or commands execute.

The deterministic fallback is a rule-based investigator, not an LLM. Evidence remains usable when no model is installed. This is an explicit product property rather than a hidden degraded mode.


## Cloud boundary

The separate `cloud.py` adapter stages private GCS inputs, restores a coherent local state bundle, scans transactionally and uploads a backup using generation preconditions. The read-only Gunicorn entrypoint has a different service account. See `infra/gcp/README.md` for consistency, IAM, size limits and deployment gates. No live SQLite file is mounted on object storage.
