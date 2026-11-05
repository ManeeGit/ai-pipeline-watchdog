# AI Pipeline Watchdog

**A local-first reliability desk for data pipelines.** Detect broken contracts, correlate downstream symptoms, and turn incident evidence into a reviewable recovery plan. Run it without an account, API key, Docker, database server, or model download.

> Production-oriented deployment candidate, not a verified production service. Detection and fallback triage work offline. Optional model integrations are advisory; the external API slot is deliberately unconfigured. No recovery action is executed. No cloud resources or paid API calls have been used.

## Production engineering track

The v0.2 hardening adds a real cloud adapter and deployable infrastructure code rather than relabeling the demo:

- A single-task Cloud Run scanner reads synthetic fixtures or explicitly configured GCS CSV inputs.
- Durable state is a coherent SQLite backup bundle in private GCS, committed with generation preconditions. No SQLite-on-GCS filesystem mount.
- A separate read-only Gunicorn dashboard is protected by Cloud Run IAM, with a distinct state-reader identity.
- Persistent scanner readiness/failure counters, content-deduplicated volume baselines, safe online backups, and evidence-preserving retention.
- Terraform for scoped identities, bounded compute, private/versioned storage, paused scheduling, monitoring alerts, and a $10 gross-cost budget template. Budget alerts are not spending caps.
- A typed external-provider hook and blank configuration example. No external model transport, API key, or paid service is activated.

Start with [the production review](docs/PRODUCTION_REVIEW.md), [GCP deployment and recovery](infra/gcp/README.md), and [threat model](docs/THREAT_MODEL.md). The local demo below still needs only Python and works without cloud access.

**Not yet verified:** real GCP rollout/IAM/alerts/recovery/costs, container build, rendered browser QA, hosted CI, or live model quality. Terraform syntax/format and signed-provider installation passed; provider-schema validation and mocked plans are blocked here by the sandbox's Unix-socket restriction and remain mandatory CI gates. A local Gunicorn worker and graceful shutdown passed using fake cloud storage.

## What it does

- Collects real CSV files and optional producer run-status metadata. Records aggregate observations, not raw rows.
- Checks freshness, schema changes, type violations, null rates, duplicate keys, empty datasets, future timestamps, row-volume shifts, and failed runs.
- Maintains a SQLite incident lifecycle: **open → resolved → reopened**, deduplicated by pipeline and check. Checks that could not run cannot silently claim recovery.
- Correlates affected stages against a validated dependency DAG. Upstream candidates include supporting incident IDs and explicit uncertainty.
- Offers eight human-reviewed recovery playbooks. An optional local language model may summarize evidence and select these playbooks, never invent executable actions.
- Serves a polished read-only dashboard with real volume history, incident evidence, lineage, recovery playbooks, and an event timeline.
- Exposes JSON reports, structured scan logs, a process-health endpoint, and Prometheus-format metrics.

## Start in under a minute

Python **3.11+**. The runtime and test suite use only the Python standard library. The following works without package installation or network access:

```bash
cd ai-pipeline-watchdog
export PYTHONPATH=src
python3 -m pipeline_watchdog demo
python3 -m pipeline_watchdog serve
```

Open **http://127.0.0.1:8765**. The demo creates three synthetic commerce pipelines, twelve healthy historical scans, and a cascading incident. Nine open checks are expected. All records are generated; no real customer data is included.

`demo` refuses to overwrite a nonempty directory. Use `--workspace another-demo` for a fresh demo and point subsequent commands to its config.

Prefer an installed CLI? Create your own virtual environment, then:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
pipeline-watchdog --help
```

Packaging may download the setuptools build backend. This is not required for the `PYTHONPATH=src` workflow.

## A two-minute demonstration

With the dashboard open, use a second terminal with `PYTHONPATH=src`:

```bash
# Explain the cascade from existing evidence. No model required.
python3 -m pipeline_watchdog explain

# Restore only the generated synthetic files and scan them.
python3 -m pipeline_watchdog scenario healthy

# Show a different failure and its evidence.
python3 -m pipeline_watchdog scenario quality-regression

# Reopen the cascade. The same incidents keep their identities.
python3 -m pipeline_watchdog scenario cascade
```

The dashboard refreshes every five seconds. Click an incident to inspect its exact evidence and observation ID. Filter resolved incidents to review recovery. Scenario commands are restricted to marked demo workspaces and must never be used on real pipeline outputs.

Seven scenarios: `healthy`, `late-arrival`, `schema-drift`, `quality-regression`, `volume-drop`, `run-failure`, and `cascade`.

## Watch your own local pipeline

Copy [the example contract](examples/watchdog.json) to a dedicated directory containing your CSV exports. Adjust paths, column contracts, keys, dependencies, and thresholds. Paths are confined to that configuration directory, including symlink resolution. The collector is read-only.

```bash
python3 -m pipeline_watchdog scan --config local-data/watchdog.json

# Three scans, 30 seconds apart. Bounded by default.
python3 -m pipeline_watchdog watch --config local-data/watchdog.json --cycles 3

# Explicit continuous operation until Ctrl+C.
python3 -m pipeline_watchdog watch --config local-data/watchdog.json --forever --interval 60

# Dashboard plus monitoring in one foreground process.
python3 -m pipeline_watchdog serve --config local-data/watchdog.json --watch --interval 60

# CI-friendly: exit 2 when any incident remains open.
python3 -m pipeline_watchdog scan --config local-data/watchdog.json --fail-on-incident

# Machine-readable handoff, written where you choose.
python3 -m pipeline_watchdog report --config local-data/watchdog.json > report.json
```

The database defaults to `watchdog.db` beside the configuration. Use a separate database for each distinct configuration. Relative data paths are relative to the config file, not your terminal directory. Timestamp values must be timezone-aware ISO 8601. Producers should publish complete files with atomic renames.

A run-status file, when configured, is a small JSON object:

```json
{"status": "success"}
```

Supported statuses: `success`, `failed`, `running`. Missing or malformed configured status files raise an availability incident. Without a status file, execution state is `unknown`; the collector does not invent run success. This prototype does not validate the age of the status file or detect a hung `running` job.

## Backup and retention

```bash
python3 -m pipeline_watchdog backup --output backup-2026-11-05.db
python3 -m pipeline_watchdog prune --retain-days 30          # Preview only
python3 -m pipeline_watchdog prune --retain-days 30 --apply  # Explicit removal of eligible history
```

Backups use SQLite's online backup API and verify integrity. Existing destinations are never overwritten. Retention preserves current observations and every snapshot referenced by incident/event evidence. `/readyz` distinguishes a recent completed scan from a merely running HTTP process.

## External API integration slot

See [the typed provider interface](src/pipeline_watchdog/providers.py), [blank configuration](.env.example), and [adapter skeleton](examples/provider_adapter.py). `ExternalAPIHook()` with no transport makes no request and returns the deterministic result with an explicit reason. These are integration points, not a secretly active remote AI feature. Choose a provider, approved destination, privacy policy, budget and secret store before implementing a transport.

## Optional local AI

Install Ollama separately from its official distribution if you want local model narration. Model installation and inference are never automatic. A quantized 1–3B model is a reasonable starting point on an 8 GB laptop; actual memory/latency depends on the model, context, and other applications.

After you have chosen and downloaded a model and started Ollama:

```bash
python3 -m pipeline_watchdog explain --provider ollama --model qwen2.5:3b --timeout 30
```

This sends **only opaque incident IDs, check categories, severity, allowlisted numeric aggregates, and allowed playbook IDs** to `127.0.0.1:11434`. No raw rows, source paths, producer logs, customer IDs, or schema field names are sent. The adapter ignores proxy settings and rejects redirects. Do not install a model you do not trust.

Responses must pass a strict JSON schema, cite known open incidents, and select only relevant predefined playbooks. Invalid, oversized, unavailable, or timed-out responses fall back to deterministic triage. Model output is untrusted narrative, not proof of diagnosis. The dashboard stays deterministic; model calls happen only through this explicit CLI command.

**Validation disclosure:** adapter behavior and fallback paths are tested with controlled fixtures. No live model quality or Apple Silicon performance result is claimed. See [the model card](docs/MODEL_CARD.md).

## Verify it

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m pipeline_watchdog evaluate
python3 -m compileall -q src tests
node --check src/pipeline_watchdog/static/app.js  # optional Node syntax check
PYTHONPATH=src python3 scripts/benchmark.py
```

- **74 unit/integration/adversarial tests** cover contracts, malformed input, incident recovery, unobservable checks, transactional rollback, data minimization, model validation/fallback, loopback HTTP, and symlink safety.
- **9 deterministic evaluation cases** pass: seven detection scenarios, recovery, and reopening. Across the synthetic scenario labels, 18 expected positive checks are detected with no false positives or misses. This is fixture correctness, not real-world accuracy or an LLM benchmark. [Full evaluation](docs/evaluation.json).
- A small Linux/Python 3.12 run measured a **7.7 ms median full scan** and **15.1 MiB peak process RSS** for three tiny pipelines across thirty scans. Browser/model memory is excluded. This is not a production sizing claim. [Measured output](docs/benchmark.json).
- CI is configured for Python 3.11–3.13, cloud imports/container checks and offline Terraform validation/mock plans. Hosted CI has not been run unless your repository's Actions page says otherwise.

Optional browser test: install Playwright and Chromium in your own development environment, run the cascade demo server, then `python3 scripts/browser_smoke.py --screenshots artifacts`. Pass `--chromium /path/to/chromium` when using a system browser. The source and HTTP endpoints were validated here, but rendered UI testing was blocked by the cloud shell's browser-process restrictions. The provided browser smoke is **not claimed as passed**.

## Design and scope

```text
CSV + status JSON → bounded collector → deterministic contracts
                                            ↓
                           SQLite snapshots + incident lifecycle
                                            ↓
                              dependency-aware investigation
                                  ↙                  ↘
                    local dashboard / metrics     explicit Ollama call
                                                     ↓
                                          validated advisory or fallback
```

- Local runtime: Python standard library, SQLite WAL, HTML/CSS/vanilla JavaScript. The optional cloud image adds pinned Google Cloud Storage SDK and Gunicorn dependencies.
- Resource boundaries: 50 pipelines; 25 MiB, 100,000 rows, 100 columns per CSV; minimum five-second scan interval; bounded historical reads; optional model response and timeout limits.
- Volume baseline: latest thirty distinct healthy file-content fingerprints, five-sample warm-up, robust median/MAD score plus a material-change threshold. Repeated scans of unchanged content do not inflate the baseline. Content identity is not a producer run ID.
- Freshness uses the newest valid event timestamp, not filesystem mtime. One fresh row can mask older partitions; partition-aware SLOs are a future extension.
- Schema means declared column names and per-value type validation. It is not inferred warehouse DDL.
- Lineage is declared, not discovered. Correlation does not establish root cause.
- The local development server is loopback-only and unauthenticated. Do not expose it through a tunnel or public interface. Cloud deployment uses a separate WSGI entrypoint and mandatory platform IAM.
- CSV-focused bounded service candidate, not a warehouse/streaming connector, distributed transactional database, paging product, or fully operated production incident manager.
- No automatic remediation, SQL execution, process launching, credential storage, cloud AI, telemetry, or external notification delivery.
- Local continuous operation requires an awake host and running process. No daemon is installed. Local retention is explicit and preview-only unless --apply is selected; the cloud job applies its configured retention while preserving incident evidence. Storage can still reach its documented cap.

Read [architecture](docs/ARCHITECTURE.md), [operating guidance](docs/OPERATIONS.md), [security](SECURITY.md), and [the demo talk track](docs/DEMO.md).

## Project layout

```text
src/pipeline_watchdog/  collector, checks, storage, triage, AI adapter, CLI, HTTP server
tests/                 unit, integration, and independent-review regression tests
examples/              synthetic contract and small CSV example
scripts/               reproducible benchmark and optional browser smoke
docs/                  architecture, operations, model card, evaluation evidence
.github/workflows/     Python-version CI matrix
```

## Next engineering steps

1. Complete the actual GCP deployment acceptance, IAM denial, alert delivery, load and restore drills.
2. Add per-partition freshness, status-file age, batch manifests and distinct producer-run IDs.
3. Add alert debouncing, maintenance windows, seasonal baselines and warehouse adapters.
4. Evaluate model factual entailment and abstention before activating any external provider.
5. Assign operational ownership, long-term recovery policy and a reviewed approval queue before any remediation integration.

These are roadmap items, not implemented capabilities.

MIT licensed. All included demo data is synthetic.
