# GCP deployment candidate

**Nothing has been provisioned. Do not run apply, build/push, scheduling or deployment commands until the project, identities, region and spending ceiling are explicitly approved.** Existing credits do not make the project free or authorize spending. Default mode is synthetic and no model API is configured.

## Resources this template would create

- One private, versioned regional GCS bucket with uniform access and public-access prevention.
- Separate keyless scanner, dashboard and Scheduler service accounts. Runtime uses attached-service-account ADC, not downloaded JSON keys.
- A one-task Cloud Run scanner job: 1 vCPU, 1 GiB, 180-second timeout, one retry.
- An IAM-protected Cloud Run dashboard: Gunicorn, scale-to-zero, maximum one instance, 512 MiB, four concurrent requests, 60-second request timeout.
- A UTC half-hour Scheduler that starts **paused**. Its identity can invoke only the scanner job.
- Failure and absent-success log metrics and monitoring alerts sent to an explicitly supplied operator email.
- A project-scoped monthly **gross-cost** budget, default $10, with 50/90/100% alerts. Credits are excluded from the calculation so they cannot hide usage. This is **not a hard spending cap**.

It expects an existing dedicated project, a billing account and an already-built Artifact Registry image pinned by SHA-256 digest. It does not create a project, registry, build service, production dataset, API key, external AI subscription, or automatic GitHub deployment.

## Storage design

Do **not** mount GCS as SQLite's live filesystem. Each scanner execution downloads one coherent state bundle to its private ephemeral directory, performs the scan and transaction, makes a SQLite online backup, and uploads a complete replacement bundle with `ifGenerationMatch`.

The bundle contains only contract JSON, aggregate SQLite state and a manifest. CSV rows are not published into the state bundle. Generation 0 creates only an absent object. A competing/stale writer receives a precondition failure and cannot overwrite committed state. The job retry starts from the latest generation. This is optimistic concurrency, not exactly-once processing.

A failed cloud job does not publish a partial failure database over the last good state. Its failure is reported through Cloud Run logs and the failure alert; the dashboard retains the last committed observation and becomes unready when that observation exceeds the age limit. Local scanner failure counters are persisted directly, but uncommitted cloud-job counters are not.

The dashboard identity can read `state/` but cannot read `inputs/`, create objects, or run jobs. It caches state for at most thirty seconds and returns 503 when a required refresh fails. The scanner can read `inputs/` and get/create/delete objects only under `state/`; replacement requires create+delete permissions. No role grants public access.

Synthetic mode seeds a clearly labeled historical fixture and regenerates current synthetic CSVs on each execution. GCS mode reads `inputs/watchdog.json` and its relative paths under `inputs/`. Real inputs require a separate authorized data-sharing and ingestion decision. Files are generation-consistent individually, but there is no cross-file batch-manifest guarantee yet.

The prototype bounds state DB size to 64 MiB, total staged inputs to 128 MiB, and each CSV to 25 MiB / 100,000 rows. Thirty-day retention removes only unreferenced old snapshots; incident/event evidence and latest snapshots are preserved. Evidence growth can therefore reach the state cap. The correct response is migration/archival, not silent evidence deletion.

## Local checks, no GCP account required

```bash
terraform init -backend=false
terraform fmt -check -recursive
terraform validate
terraform test
```

The mock tests assert paused scheduling, single-task execution, bounded scale, private storage, no implicit dashboard users, credit-aware budgets, and rejection of public principals/mutable image tags. These tests do not create cloud resources.

**Current verification:** HCL parses, Terraform format passes, and the signed Google provider was installed with its lockfile. Provider validation and mocked Terraform tests could not run here because the execution sandbox disallows the provider's Unix IPC socket. They are mandatory CI/deployment gates, not claimed passes. No plan against a real account or apply has run.

## Approved deployment procedure

1. Choose a dedicated project and explicit operator identities. Confirm region, data classification, budget and who receives alerts. Verify billing permissions; budget creation often needs billing-account permissions beyond project ownership.
2. Complete local/CI tests, container vulnerability review, and Terraform validation/mock tests. Resolve any provider-schema or organization-policy issues first.
3. Build the Docker image through an approved build workflow and push it to an existing Artifact Registry repository. Use a builder identity scoped to that repository. Record its immutable digest. Docker build and Cloud Build were not run here.
4. Copy `terraform.tfvars.example` into an ignored private `.tfvars` file. Replace all placeholders. Leave `scheduler_paused = true` and `input_mode = "synthetic"`. Do not add `allUsers` or `allAuthenticatedUsers`.
5. Configure approved operator authentication. Use a separately approved remote Terraform state backend with access control and locking for shared operation; the template intentionally does not bootstrap its own state backend or write credentials.
6. Run and inspect `terraform plan`. Confirm all identities, bucket rules, image digests, alert recipients and financial effects. Apply only after the resulting changes are approved.
7. Execute the scanner job once manually. Verify completion, `state_committed` structured log, state object generation, state bundle manifest and no unexpected external requests.
8. Confirm anonymous requests to `/api/summary` are rejected at the Cloud Run IAM edge. Use an authorized identity token for API verification, or `gcloud run services proxy` for local browser access. The application relies on platform IAM; environment variables alone do not authenticate a deployment.
9. Run `scripts/check_deployment.py --url <verified-service-origin>` with an identity token supplied via `WATCHDOG_ID_TOKEN`. The script does not fetch or print credentials. Test both an authorized and an unauthorized account separately.
10. Run the recovery drill below and verify alert delivery. Absence alerts require an initial successful metric time series; an untouched deployment may not alert.
11. Only then enable Scheduler through a reviewed Terraform change. Observe at least a full day of scheduled executions, memory, errors, storage growth, costs and incident lifecycle before treating it as an operational service.

Never grant broad Owner/Editor roles to runtime accounts or disable invoker checks to make a broken deployment work. GCS bucket names are globally unique; adapt naming if the planned name is unavailable.

## Recovery drill

1. Pause Scheduler and confirm no execution is currently writing state. Record the current object generation and immutable image digest.
2. Download a selected prior version of `state/watchdog.bundle` using an authorized operator. Preserve the current version separately.
3. Verify ZIP members, SQLite integrity, configuration version, latest scan time and incident/event references in an isolated workspace. Run the same binary/image version used to create it, or a tested migration.
4. Re-publish the verified backup as a new current generation using a generation precondition matching the current object. Do not blindly delete current state.
5. Execute one synthetic scanner job; verify successful commit, current readiness, preserved incident identities and expected recovery behavior.
6. Restore scheduling only after the operator approves the result. Record the measured recovery time and data loss window.

Versioning keeps approximately the latest 49 generations. At a thirty-minute cadence that is about one day, less if operators run extra jobs. Soft delete is deliberately disabled to avoid a hidden extra copy-retention bill. This cost/recovery tradeoff is explicit; it is not immutable disaster recovery. Add separately approved, tested long-term backups before handling critical data.

## Cost controls and limitations

Scheduler starts paused; no API model is enabled; dashboard minimum instances are zero and maximum is one; the job is bounded to one task, one retry, three minutes; reads and uploads are bounded. Old state generations are lifecycle-limited. These reduce exposure but **do not cap the bill**. Sustained authorized dashboard traffic, job failures, logging, builds, registry storage, network egress and retained object copies can still cost money.

The $10 budget is an alert threshold, not a $10 guarantee. Notifications can be delayed. Credits may expire, exclude services, or be consumed by other workloads. Verify current GCP pricing and credit conditions before applying. A budget alert should prompt an operator to pause Scheduler, stop active executions and review dashboard access; this repository does not automatically disable billing or delete data.

No uptime, recovery-time, cloud cost, model quality, multi-user authorization, or production workload guarantee is claimed before deployment acceptance and an observation period.
