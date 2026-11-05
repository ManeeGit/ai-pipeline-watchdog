import unittest
from pipeline_watchdog.providers import DeterministicProvider, ExternalAPIHook


class ProviderSlotTests(unittest.TestCase):
    def setUp(self):
        self.items = [{"id": "known", "check": "freshness", "severity": "warning", "status": "open", "evidence": {"freshness_minutes": 120}, "runbook": "restore-freshness"}]
        self.fallback = {"provider": "deterministic", "summary": "Review freshness"}

    def test_default_provider_has_no_external_dependency(self):
        self.assertIs(DeterministicProvider().explain(self.items, self.fallback), self.fallback)

    def test_empty_api_slot_makes_no_request(self):
        result = ExternalAPIHook().explain(self.items, self.fallback)
        self.assertEqual(result["provider"], "deterministic")
        self.assertIn("no request", result["fallback_reason"])

    def test_injected_transport_is_minimized_and_validated(self):
        def transport(payload):
            self.assertEqual(set(payload[0]), {"id", "check", "severity", "metrics", "allowed_runbook"})
            return {"summary": "Review the evidence.", "evidence_ids": ["known"], "runbook_ids": ["restore-freshness"], "uncertainty": "Cause remains unverified."}
        result = ExternalAPIHook(transport).explain(self.items, self.fallback)
        self.assertEqual(result["provider"], "external-api-hook")
        self.assertTrue(result["advisory_only"])

    def test_bad_api_slot_cannot_invent_an_action(self):
        result = ExternalAPIHook(lambda data: {"command": "delete everything"}).explain(self.items, self.fallback)
        self.assertEqual(result["provider"], "deterministic")
