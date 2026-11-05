# Validation record

Local verification on Linux with Python 3.12.14, 2026-11-05.

## Passed

- 74 standard-library unittest cases, including end-to-end fixture evaluation and four independent source-review regressions.
- Nine evaluation scenarios: healthy, late arrival, schema drift, quality regression, volume drop, failed run, cascading failure, recovery, and reopening without duplicate incidents.
- Python source/test compilation.
- JavaScript syntax check using Node.
- Offline wheel build, installation into an isolated target directory, CLI import, and static asset inclusion.
- Minimal example collection, producing the expected stale-data finding.
- Two foreground monitoring cycles five seconds apart, with unchanged incident IDs and no duplicated transitions.
- Optional Ollama request with no running model service, returning a labeled deterministic fallback.
- Loopback HTTP integration tests for summary, process liveness, metrics, static assets, Host validation, traversal rejection, mutation rejection and security headers.
- Thirty-scan tiny-fixture microbenchmark, reported separately in `benchmark.json`.

## Source-review issues fixed and regression-tested

- Invalid unhashable producer status values are handled as availability evidence rather than crashing the scan.
- Demo CSV publishing uses exclusive randomly named temporary files; predictable temp symlinks cannot overwrite an outside file.
- Dense DAG ancestor computation is memoized and tested with fifty pipelines.
- Checks blocked by missing prerequisite columns cannot falsely resolve prior incidents.
- Affected stages are presented in dependency order rather than alphabetical order.

## Additional v0.2 checks passed

- Persistent scanner failure/readiness and recovery across process reconstruction.
- Content-deduplicated baselines, safe backup/restore and evidence-preserving retention.
- GCS-compatible adapter tests with fake object storage, including two concurrent scanner attempts with exactly one successful generation commit.
- Read-only cloud WSGI routes, failure-to-503 behavior, bundle traversal/size controls, input-mode and contract-change protections.
- External API provider hook defaults to no transport and no request; injected fixture transports must pass the same evidence/runbook validation.
- Pinned Google Cloud Storage 3.17.1 and Gunicorn 26.2.0 installed into an isolated test target and imported without cloud credentials.
- A real local Gunicorn worker served a synthetic cascade and readiness successfully, then exited cleanly on SIGTERM. Fake object storage was used; no cloud request occurred.
- Terraform 1.10.5 official binary checksum verification, HCL parsing, formatting and signed Google provider 6.50.0 installation with checked-in lockfile. These are not provider-schema or deployment verification.

## Not verified

- Rendered browser/mobile appearance and interactive browser smoke: the shell's Chromium process could not create required local sockets; the separate supported cloud browser could not reach that shell's loopback server. HTTP behavior and JavaScript syntax passed, but those are not visual or accessibility testing.
- Live Ollama inference, model reasoning quality, real prompt-injection robustness, or model memory/latency.
- Apple Silicon or an actual 8 GB Mac.
- Hosted GitHub Actions, container build, GCP deployment/IAM/alert delivery/costs/recovery, remote warehouse integration, production data volume or real-world alert precision.
- Dependency vulnerability audit: pip-audit installed successfully, but its advisory request to PyPI timed out. No vulnerability-clean result is claimed.
- Terraform provider validation and mocked plans: the provider cannot open its required Unix IPC socket in this sandbox, including after an escalated attempt. CI contains these mandatory checks. No real-account Terraform plan or apply occurred.

The provided browser-smoke script can be run in a development environment with an available Chromium. The default project workflow requires neither a browser automation package nor a language model.
