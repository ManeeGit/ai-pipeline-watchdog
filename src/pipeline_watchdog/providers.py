"""Provider extension point. External APIs are deliberately unconfigured and never called by default."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from .ai import explain_with_ollama, model_evidence, validate_response


class TriageProvider(Protocol):
    def explain(self, incidents: list[dict], fallback: dict) -> dict: ...


@dataclass(frozen=True)
class DeterministicProvider:
    def explain(self, incidents: list[dict], fallback: dict) -> dict:
        return fallback


@dataclass(frozen=True)
class OllamaProvider:
    model: str = "qwen2.5:3b"
    timeout_seconds: float = 15

    def explain(self, incidents: list[dict], fallback: dict) -> dict:
        return explain_with_ollama(incidents, fallback, self.model, self.timeout_seconds)


@dataclass(frozen=True)
class ExternalAPIHook:
    """A deliberate empty integration slot, not a fake functioning cloud AI feature.

    Supply an explicitly authorized transport that accepts minimized evidence and returns
    the four-field response contract. The transport owns credentials, approved destination,
    deadlines, response-size limits, and request budgets. No transport is shipped or invoked.
    """
    transport: Callable[[list[dict]], dict] | None = None

    def explain(self, incidents: list[dict], fallback: dict) -> dict:
        if self.transport is None:
            return dict(fallback, fallback_reason="External API integration is not configured; no request was made.")
        try:
            result = validate_response(self.transport(model_evidence(incidents)), incidents)
            result["provider"] = "external-api-hook"
            return result
        except Exception:
            return dict(fallback, fallback_reason="External API adapter failed validation or transport; deterministic evidence retained.")
