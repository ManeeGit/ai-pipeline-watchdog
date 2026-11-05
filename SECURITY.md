# Security scope

The local development server is single-user and loopback-only. Do not expose it to other devices, public networks, reverse proxies or tunnels. It has no authentication. The separate cloud entrypoint requires verified Cloud Run IAM and distinct runtime identities as documented in infra/gcp. Application-level multi-tenant authorization is not implemented.

## Built-in boundaries

- Inputs are constrained to the configuration directory after symlink resolution.
- CSV bytes, rows, columns and header lengths are bounded; status/config files have size caps.
- SQLite uses parameterized SQL, transactions, closed connections and owner-only database-file permissions.
- Dashboard binds only to IPv4 loopback, validates Host, rejects writes, disables CORS, and applies CSP, anti-framing and MIME-sniffing protections.
- Source values are not rendered as HTML or saved as row samples. The frontend uses `textContent`.
- Model requests are explicit, local-only, proxy-free, redirect-free and minimized. Model responses cannot invoke tools, shell, SQL or filesystem changes.
- Demo scenarios require a generated marker. Data-file symlinks escaping the workspace are rejected. CSV temporary files are created exclusively with random names.
- No secrets, credentials, real customer data, or external notifications are included.

## Threat assumptions and remaining risks

The directory and local OS account are trusted. This is not a hardened sandbox against another process racing directory symlinks or replacing files concurrently. Avoid world-writable workspace directories. The HTTP service is intended for trusted local users; it lacks production rate limiting, audit authentication, TLS and a hardened web-server runtime.

Aggregate data and schema metadata can still be sensitive. Keep the workspace private and review any exported report before sharing it. Databases are not encrypted at rest. The read-only server exposes metadata to processes/users able to reach that loopback service.

A local model can hallucinate or follow malicious narrative despite input minimization. Strict reference validation does not validate factual entailment. Never paste generated text into a shell or apply recovery advice without review.

Source paths are checked at access time, but no operating-system namespace isolation is provided. SQLite history grows without retention. A sufficiently large or hostile valid dataset can still consume substantial CPU/memory within configured caps.

## Reporting a problem

Do not include secrets or private data in public issues. Describe the affected version, a minimal synthetic reproduction, and the security boundary involved. If the repository host supports private vulnerability reporting, use that channel for exploitable findings.

## Validation

The test suite covers path traversal, symlink escape, predictable-temp-file attacks, malformed inputs, response allowlists, DNS-rebinding Host rejection, write-route rejection and atomic persistence. Tests are not a security certification. See README for checks actually run and remaining validation limits.


## Cloud deployment

See docs/THREAT_MODEL.md and docs/PRODUCTION_REVIEW.md for cloud trust boundaries, scoped identities, generation-precondition writes, recovery, billing risk and remaining validation gates. Infrastructure code is not evidence that a live deployment enforces its intended policy.
