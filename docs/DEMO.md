# Demo and interview talk track

## The problem

A pipeline can finish successfully while delivering stale, incomplete, duplicated or incompatible data. Dashboards full of independent alerts make operators reconstruct the dependency chain themselves. This project creates a small local control room with explicit evidence and an intentionally narrow AI boundary.

## Walkthrough

1. Run `demo` in a new workspace. It creates twelve historical healthy observations and a cascading failure.
2. Open the dashboard. Compare raw orders, cleaned orders, and daily revenue. Inspect the actual row-volume sparklines.
3. Open the raw schema incident: the expected `amount` field has been replaced by `gross_amount`.
4. Review stale watermarks, volume reductions, cleaned-data nulls and duplicate keys, and the downstream failed run.
5. Explain why `orders_raw` is an upstream **candidate**, not a proven cause. The graph is declared and the evidence supports correlation.
6. Show `explain` without a model. It returns useful bounded playbooks rather than pretending to be generative AI.
7. Optionally demonstrate explicit Ollama narration if a trusted model is already installed. Discuss payload minimization, citation validation, fallback, and the distinction between valid references and true statements.
8. Run `scenario healthy`. The same incidents resolve and the event timeline records recovery.
9. Run `scenario cascade`. Their identities are reused; the audit trail shows reopening rather than duplicate alert spam.
10. Run the test suite and fixture evaluation. Be precise: the scores prove coverage of synthetic fixtures, not production accuracy.

## Engineering choices worth discussing

- Why deterministic contracts own detection while a model only narrates evidence.
- Why missing prerequisites cannot prove recovery, and how evaluated-check coverage prevents false resolution.
- Why immutable snapshots and state-transition events are more useful than logging every alert repeatedly.
- Why local execution and zero runtime dependencies help an 8 GB developer laptop.
- Why a baseline needs both robust deviation and a meaningful magnitude threshold.
- Why parent-directory containment alone does not make predictable temporary files safe.
- Why memoizing DAG ancestors matters even for a 50-pipeline limit.

## Honest next steps

Per-partition freshness, unique-run identifiers, status freshness, seasonal volume models, debounce windows, retention, read-only database adapters, model factual-support evaluation, and authenticated alerting are future work. No warehouse or production connector has been silently simulated.
