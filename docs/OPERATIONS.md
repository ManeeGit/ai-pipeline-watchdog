# Operating the local prototype

## Ownership and lifecycle

Keep each configuration, input directory, and SQLite database in a private directory owned by one trusted user. Never point scenario commands at production data. The collector reads input files; it does not repair them. For ongoing operation, keep the machine awake and the foreground `watch --forever` or `serve --watch` process running. Ctrl+C stops it. There is no auto-start service, external alerting, or availability guarantee.

Use a dedicated, new database when changing pipeline identity or materially changing contracts. Removed pipelines remain in history; do not reuse one database across unrelated environments. The application filters current UI pipelines but historical scan counters/events are database-wide.

## Input publishing

Write to a temporary file in the same directory, then rename it atomically into place. A collector reads at most 25 MiB from the selected source for a stable in-memory parse. The file limits are prototype guardrails, not a large-scale streaming implementation. A parse failure leaves previous incidents unresolved rather than claiming healthy data.

Timestamps require explicit offsets (`Z` or `+00:00`). Freshness is based on the maximum event timestamp. No complete-partition guarantee follows from that metric. Date-only and naive datetime values are rejected. Values named `NULL` are ordinary strings; only blank/whitespace strings count as null. Key equality is exact string equality. Numeric `NaN` and infinity fail the number contract.

All declared columns share one null threshold in this version. Extra columns are rejected unless `allow_extra_columns` is true. Missing columns always fail the schema contract. Unexpected type values produce aggregate invalid-count evidence without storing the values.

## Observability

- `GET /readyz`: recent completed scan and no recorded scanner failure. Data-contract health is separate.
- `GET /healthz`: HTTP-process liveness only. It does not prove data freshness or monitoring progress.
- `GET /api/summary`: latest observations, bounded history, incident evidence, triage and recent events.
- `GET /metrics`: unresolved incidents, persisted scans, latest collection/detection duration, health, row counts and freshness by pipeline.
- `--verbose` before the command emits JSON `scan_completed` log events. Watch mode also prints each result to stdout.
- `report` writes a full JSON summary to stdout; redirect it into a file if needed.
- `scan --fail-on-incident` exits 2 for open incidents, 1 for operational/configuration failures, and 0 when healthy. Collection failures are persisted as incidents rather than treated as a fatal CLI error.

The dashboard explicitly distinguishes being connected to HTTP from a recent scan. It warns if the latest local scan is older than five minutes. In cloud mode it uses the configured scanner-readiness age, default 65 minutes for a thirty-minute schedule. These operational indicators are separate from per-pipeline freshness SLOs.

## Disk and recovery

Snapshot history grows with every scan. Reads are bounded. The local prune command previews eligible deletions unless --apply is selected; the cloud adapter applies configured retention. Current observations and incident/event evidence are preserved, so growth is not eliminated. Monitor disk space, choose a practical interval, and archive complete workspace copies when the process is stopped. SQLite backup tooling or a cleanly stopped database copy is safer than copying an active WAL database piecemeal. Do not manually edit incident rows while the process runs.

Schema versions 1 and 2 are recognized. An additive v1→v2 migration preserves existing snapshots/incidents and creates runtime/baseline tables; the content-based baseline warms up from new distinct inputs. Unknown versions are rejected before schema changes. This is not a general multi-version migration framework. Keep backups before upgrading a future release. Restore a separate workspace to validate a backup before replacing current state.

## Troubleshooting

- **Demo already exists:** choose a new directory or use `scenario` on the existing generated demo. The tool intentionally does not delete existing work.
- **Source availability incident:** check configured relative paths, file permissions, CSV shape and optional status JSON.
- **No volume alerts yet:** five distinct healthy file-content samples are required. Repeated polling of the same content does not add baseline weight.
- **Dashboard does not change:** `serve` alone reads existing state. Run `scan`/`scenario`, a separate `watch`, or `serve --watch`.
- **Local AI falls back:** verify Ollama is listening on port 11434 and that the selected model is already installed. Timeout, transport, oversized or invalid responses all preserve deterministic output.
- **Port already in use:** use `serve --port 8766` and open that exact loopback URL.
- **Freshness alerts after leaving the demo overnight:** expected. These are static generated files, not a background commerce simulator. Run `scenario healthy` or `scenario cascade` to regenerate their timestamps.

## 8 GB laptop guidance

Start with deterministic mode. The project has no resident model, dataframe engine, JVM, Docker stack, or dependency services. The included microbenchmark uses only tiny fixtures and cannot predict your full workload. Open one dashboard tab, choose a 30–60 second interval, and avoid unnecessary repeated model loading. Optional inference may consume several GB; other applications and the OS need headroom. No Apple Silicon benchmark was run.
