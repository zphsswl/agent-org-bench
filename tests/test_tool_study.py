import unittest
from orgbench.tool_study import Transport
from orgbench.provider import ProviderError


class FakeProvider:
    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.calls = 0
    def complete(self, *args, **kwargs):
        self.calls += 1
        value = next(self.outcomes)
        if isinstance(value, Exception):
            raise value
        return value


class TransportTests(unittest.TestCase):
    def test_explicit_rejection_can_recover_but_unknown_usage_is_not_hidden(self):
        base = FakeProvider([ProviderError("http_error", "rejected", status=429), {"text": "ok"}])
        waits = []
        result = Transport(base, sleeper=waits.append).complete("s", "p", 16)
        self.assertEqual(result["transport_attempts"], 2)
        self.assertTrue(result["prior_attempt_usage_unknown"])
        self.assertEqual(waits, [3])

    def test_unknown_timeout_is_never_retried(self):
        base = FakeProvider([ProviderError("network_error", "unknown"), {"text": "ok"}])
        with self.assertRaises(ProviderError):
            Transport(base, sleeper=lambda _: None).complete("s", "p")
        self.assertEqual(base.calls, 1)

    def test_rejected_requests_have_finite_retry_bound(self):
        base = FakeProvider([ProviderError("http_error", "rejected", status=429)] * 3)
        with self.assertRaises(ProviderError):
            Transport(base, sleeper=lambda _: None).complete("s", "p")
        self.assertEqual(base.calls, 3)


if __name__ == "__main__":
    unittest.main()
