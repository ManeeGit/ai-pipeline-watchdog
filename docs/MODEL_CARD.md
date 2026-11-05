# Optional triage model card

## Intended use

Summarize existing data-reliability incident evidence for a human operator. Select relevant **predefined** recovery playbooks. Never authorize changes or establish a proven root cause.

## Providers

- Default: deterministic rule-based investigator. It is not a generative model.
- Optional: an already-installed model served by Ollama on `http://127.0.0.1:11434/api/chat`. `qwen2.5:3b` is the configurable default model identifier, not a bundled dependency or a guarantee of quality.
- External API: a typed provider protocol and deliberately empty transport hook are provided. No remote client, API key or paid service is configured. Fixture transports can be injected for contract tests; real integration remains an explicit future decision.

## Inputs and privacy

Inputs contain opaque incident IDs, check names, severity, allowlisted numeric metrics, and relevant playbook IDs. They omit raw data, schema names, pipeline names, source paths, credentials, and producer logs. No external request occurs in the default path. Ollama is a separate process; users are responsible for the trust and telemetry behavior of their chosen server/model distribution.

## Output contract

Exactly four model fields: `summary`, `evidence_ids`, `runbook_ids`, `uncertainty`. Bounded narrative lengths. IDs must reference supplied open incidents and associated playbooks. Unsupported fields, ungrounded references, duplicate IDs, missing citations for open incidents, oversized responses, invalid JSON and invalid types are rejected.

Narrative can still contain hallucinations or unsafe suggestions. Citation validity checks membership, not factual entailment. Narratives must remain advisory. The executable recovery surface is empty, and actual listed playbook steps come from application-owned text rather than model output.

## Inference controls

Explicit CLI invocation; fixed loopback destination; disabled proxies; denied redirects; default 15-second socket timeout; configurable maximum 120 seconds; 64 KiB response cap; 600-token generation target; 4096-token context target; temperature zero; unload request after generation. Server implementations may interpret generation settings differently. Socket timeout bounds individual blocking network operations, not a strict whole-process deadline.

No retries. Any supported failure retains deterministic evidence with a visible fallback reason. No credentials are required or stored.

## Evaluation status

The test suite exercises response validation, unsupported citations/actions, data minimization, timeout bounds, and transport fallback. The nine-case fixture evaluation measures deterministic detection and incident lifecycle, not language-model reasoning.

A live Ollama inference, hallucination rate, model safety benchmark, and Mac memory benchmark have **not** been run. Before operational use, create held-out incidents with independent labels, score citation support and factual entailment, test adversarial narratives, measure abstention, and record model/version/quantization and hardware.

## Out-of-scope use

Autonomous remediation, financial or medical decisions, production paging ownership, access-control decisions, automated SQL execution, remote credential handling, and diagnosis from secret production logs.
