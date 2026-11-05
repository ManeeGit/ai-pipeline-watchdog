# Threat model and trust boundaries

## Assets

Aggregate incident evidence, source schema metadata, GCS state versions, runtime identity permissions, API credentials if added later, and billing capacity. Synthetic is the default; real data has not been authorized.

## Boundaries and mitigations

- **Producer → scanner:** bounded UTF-8 CSV/config/status parsing, explicit contracts, path containment, fixed staging budgets, no row persistence. Malformed values become evidence or a failed job. Producer strings never become shell commands or SQL.
- **Scanner → state:** parameterized SQL and transaction rollback; consistent SQLite backup; fixed ZIP members; GCS checksum and generation preconditions. A stale writer cannot silently overwrite a newer result. No bucket-mounted SQLite.
- **State → dashboard:** dedicated object-reader identity, no inputs access, no cloud writes, fixed bundle members and size limits, escaped text, CSP, no mutation endpoint. Failure to refresh returns unavailable rather than claiming current health.
- **Client → cloud edge:** Cloud Run IAM must reject anonymous callers. Terraform permits only named user/group/service-account invokers. Service-account keys are not created. Local browser access can use an authenticated Cloud Run proxy.
- **Scheduler → job:** separate service account scoped to job invocation; one task, one retry, timeout and paused initial state.
- **Evidence → model:** deterministic by default. The optional local adapter minimizes payloads and constrains references/playbooks. External integration is an empty typed hook; credentials and transport do not exist until explicitly supplied.
- **Source → release:** pinned image digest required by Terraform; pinned dependency versions; CI gates; operator-reviewed plan. Build signing, artifact provenance and vulnerability results remain deployment gates.

## Residual risks

A privileged runtime or project administrator can modify code, bucket state or IAM. An approved reader can export metadata. Model narratives may hallucinate despite valid IDs. An authorized caller can generate cloud charges. Directory races are outside the local trusted-user threat model. Budget alerts lag. Versioning is not immutable offsite backup. A malformed or malicious SQLite database from a compromised writer can deny service; SQLite and dependencies require patching.

There is no multi-tenant isolation, per-user application audit, field-level authorization, VPC service perimeter, customer-managed encryption key integration, or compliance certification. GCP-managed encryption and authenticated transport do not by themselves satisfy regulatory obligations.

## Abuse and fault tests

Tests cover path traversal/symlink escape, predictable temporary-file attacks, malformed status/CSV, dense graphs, unsupported model references/actions, missing prerequisite checks, transaction rollback, backup collision, retention references, stale scanner readiness, conflicting GCS state writers, unavailable storage, archive traversal, input-mode/contract changes and reserved staging paths. Real IAM denial, cloud throttling, quota exhaustion and restore drills still require an approved deployment.
