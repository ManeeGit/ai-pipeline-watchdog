"""Future API integration slot. This example deliberately makes no HTTP request."""
from pipeline_watchdog.providers import ExternalAPIHook


def authorized_transport(minimized_evidence: list[dict]) -> dict:
    # Implement only when an operator explicitly chooses a provider and spending limit.
    # 1. Read the API key from a secret store, never from source control.
    # 2. Use the approved HTTPS destination, no redirects, a strict deadline and size cap.
    # 3. Enforce a request/token budget; never retry an uncertain paid request blindly.
    # 4. Return exactly summary, evidence_ids, runbook_ids, and uncertainty.
    # 5. Run held-out factual-support, abstention and adversarial evaluations before release.
    raise NotImplementedError("No paid or external model integration has been activated")


provider = ExternalAPIHook()  # Intentionally no transport. Always safe deterministic fallback.
