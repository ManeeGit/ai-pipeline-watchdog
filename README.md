# AI Pipeline Watchdog

**A local-first reliability desk for data pipelines.** Detect broken contracts, correlate downstream symptoms, and turn incident evidence into a reviewable recovery plan. Run it without an account, API key, Docker, database server, or model download.

> Functional portfolio prototype, not an autonomous production operator. Detection and fallback triage are deterministic. Optional Ollama inference is explicit, local-only, and advisory. No recovery action is executed.

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

- **53 unit/integration/adversarial tests** cover contracts, malformed input, incident recovery, unobservable checks, transactional rollback, data minimization, model validation/fallback, loopback HTTP, and symlink safety.
- **9 deterministic evaluation cases** pass: seven detection scenarios, recovery, and reopening. Across the synthetic scenario labels, 18 expected positive checks are detected with no false positives or misses. This is fixture correctness, not real-world accuracy or an LLM benchmark. [Full evaluation](docs/evaluation.json).
- A small Linux/Python 3.12 run measured a **5.7 ms median full scan** and **14.8 MiB peak process RSS** for three tiny pipelines across thirty scans. Browser/model memory is excluded. This is not a production sizing claim. [Measured output](docs/benchmark.json).
- CI is configured for Python 3.11–3.13. Hosted CI has not been run unless your repository's Actions page says otherwise.

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

- Runtime: Python standard library, SQLite WAL, HTML/CSS/vanilla JavaScript.
- Resource boundaries: 50 pipelines; 25 MiB, 100,000 rows, 100 columns per CSV; minimum five-second scan interval; bounded historical reads; optional model response and timeout limits.
- Volume baseline: latest thirty healthy observations, five-observation warm-up, robust median/MAD score plus a material-change threshold. Repeated scans of the same file count as observations, not unique producer runs.
- Freshness uses the newest valid event timestamp, not filesystem mtime. One fresh row can mask older partitions; partition-aware SLOs are a future extension.
- Schema means declared column names and per-value type validation. It is not inferred warehouse DDL.
- Lineage is declared, not discovered. Correlation does not establish root cause.
- Local-only, no authentication. Do not expose the built-in HTTP server through a tunnel, public interface, or reverse proxy.
- CSV-focused prototype, not a warehouse/streaming connector, distributed scheduler, paging service, or production incident manager.
- No automatic remediation, SQL execution, process launching, credential storage, cloud AI, telemetry, or external notification delivery.
- Continuous operation requires an awake host and a running process. Nothing is installed as a daemon. History grows on disk; no automatic retention/deletion is implemented.

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

1. Add per-partition freshness, status-file age, and distinct-run IDs.
2. Add retention, alert debouncing, maintenance windows, and seasonal baselines.
3. Add read-only warehouse adapters with explicit connection/credential boundaries.
4. Evaluate model factual entailment and abstention on held-out incident narratives.
5. Add authenticated alert delivery and a reviewed approval queue before considering any remediation integration.

These are roadmap items, not implemented capabilities.

MIT licensed. All included demo data is synthetic.
