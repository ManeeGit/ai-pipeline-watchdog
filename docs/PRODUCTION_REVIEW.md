# Production engineering review

This release is a **production-oriented deployment candidate**, not a verified production service. The distinction is evidence-based: useful engineering controls are implemented and tested locally; cloud rollout and real operational acceptance have not occurred.

## Implemented and locally exercised

- Deterministic contracts, isolated collection errors, deduplicated incidents and coverage-aware recovery.
- Transactional SQLite, explicit connection closure, private files, schema-version checks and v1→v2 additive migration.
- Durable scanner attempt/completion/failure state and readiness distinct from HTTP-process liveness.
- Content-fingerprinted healthy baselines: repeated polling of an unchanged CSV cannot manufacture warm-up samples.
- Online backup with integrity verification and no overwrite; retention preview by default, with explicit apply and preservation of incident/event evidence.
- Cloud adapter for GCS source objects and atomic state bundles; compare-and-swap generation preconditions; conflicting writers cannot clobber state.
- Read-only Gunicorn WSGI cloud presentation, bounded state cache, failure-to-503 behavior, no raw rows in state bundles.
- Non-root Docker recipe, pinned cloud dependencies, private IAM/Terraform design, scale limits, paused scheduling, alert and budget templates.
- Offline provider protocol and deliberately empty external API integration slot. No API key or paid model is required or invoked.
- Contract/adversarial tests and documented deployment/recovery gates. A real local Gunicorn worker and graceful SIGTERM were exercised with synthetic in-memory object storage.

## Gates still required before production use

1. **Infrastructure correctness:** Terraform provider validation and mocked plans must run successfully in CI. HCL/format passed locally, but Unix-socket restrictions blocked the provider process. Then review a real plan against the selected organization's policies and quotas.
2. **Container delivery:** Build, scan, sign/attest where appropriate, publish an immutable image, and verify that exact digest is deployed. The Docker daemon was unavailable here. Transitive dependencies are pinned, but the local advisory audit timed out. No vulnerability-clean result is claimed; scanning and update automation remain release gates.
3. **Authentication:** Verify Cloud Run invoker IAM is actually enabled, anonymous requests are rejected, approved identities work and unapproved identities fail. The local desktop server remains loopback-only and unauthenticated; it is never the cloud entrypoint.
4. **Operational acceptance:** Run real Cloud Run jobs, validate GCS generations/IAM, simulate overlap and storage failure, observe Scheduler execution, and demonstrate alert delivery and stale-state detection.
5. **Recovery:** Perform the documented object-version and SQLite restore drill; record actual RPO/RTO. Configure independently authorized long-term backups if required.
6. **Real inputs:** Obtain explicit authorization, classify data, establish producer contracts and batch-consistent manifests, validate skew/late partitions, define ownership and SLOs, and load-test representative files. None of the current scores represent real organizational data.
7. **AI:** The external API slot is intentionally unconfigured. Before connecting it, choose provider/destination, budget, secret handling, privacy rules, deadlines and retry semantics. Evaluate factual support, abstention and prompt injection on held-out incidents. Valid citations alone do not prove truth.
8. **Capacity:** Measure memory/latency at limits, concurrent reads, GCS refresh/egress behavior, cold starts and history growth. Move to a managed transactional database before exceeding the stated small single-writer/state-size boundary.
9. **Maintenance:** Assign an operator, incident procedures, patch cadence, dependency review, audit retention, and billing ownership. A codebase alone cannot provide these organizational controls.

## Deliberate limits

- No autonomous SQL, shell, data mutation or recovery execution.
- No production input access, service deployment, cloud spend or external model call has been authorized/executed here.
- GCS state is optimistic single-writer-style coordination, not a distributed high-availability database or exactly-once pipeline.
- GCS source files are individually generation-consistent; cross-file batch consistency remains a production gate.
- Current schema health is per-file, freshness uses the maximum event time, and null thresholds are per-pipeline rather than per-column.
- No seasonality model, maintenance suppression, high-volume streaming connector, per-user app RBAC or customer-facing tenant isolation.
- The cloud dashboard trusts verified platform IAM. It is not safe to redeploy it behind an unauthenticated generic web server.
- Budget alerts and maximum instances constrain risk but are not hard monetary caps.
