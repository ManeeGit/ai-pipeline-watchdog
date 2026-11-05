# Validation record

Local verification on Linux with Python 3.12.14, 2026-11-05.

## Passed

- 53 standard-library unittest cases, including end-to-end fixture evaluation and four independent source-review regressions.
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

## Not verified

- Rendered browser/mobile appearance and interactive browser smoke: the shell's Chromium process could not create required local sockets; the separate supported cloud browser could not reach that shell's loopback server. HTTP behavior and JavaScript syntax passed, but those are not visual or accessibility testing.
- Live Ollama inference, model reasoning quality, real prompt-injection robustness, or model memory/latency.
- Apple Silicon or an actual 8 GB Mac.
- Hosted GitHub Actions, deployment, remote warehouse integration, production data volume or real-world alert precision.

The provided browser-smoke script can be run in a development environment with an available Chromium. The default project workflow requires neither a browser automation package nor a language model.
