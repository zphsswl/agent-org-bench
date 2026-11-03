from __future__ import annotations

import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import urllib.error

from orgbench.architectures import ARCHITECTURES, parse_answer, run_architecture
from orgbench.provider import Provider, ProviderError, _NoRedirect


TASK = {"id": "toy", "family": "evidence", "prompt": "Select the authoritative record.",
        "schema": {"selected": "string"}, "public": {"records": ["A", "B"]},
        "metadata": {"size": 2}, "private": {"answer": "TOP_SECRET_HIDDEN_ANSWER"}}


class StubProvider:
    def __init__(self, responses=None, full_budget=False, fail_at=None):
        self.requests = []
        self.responses = responses
        self.full_budget = full_budget
        self.fail_at = fail_at

    def complete(self, system, prompt, max_tokens=None):
        index = len(self.requests)
        self.requests.append({"system": system, "prompt": prompt, "max_tokens": max_tokens})
        if self.fail_at == index:
            raise RuntimeError("credential-secret-must-not-be-copied")
        text = (self.responses[index] if self.responses is not None
                else '{"selected":"A"}')
        return {"text": text, "input_tokens": 100,
                "output_tokens": max_tokens if self.full_budget else min(10, max_tokens),
                "latency_s": 0.01, "model": "stub", "request_id": str(index)}


class OrganizationTests(unittest.TestCase):
    def test_parser_accepts_only_json_object(self):
        self.assertEqual(parse_answer('```json\n{"a":1}\n```'), {"a": 1})
        self.assertIsNone(parse_answer('[1,2]'))
        self.assertIsNone(parse_answer('prefix {"a":1} suffix'))
        self.assertIsNone(parse_answer('__import__("os").system("false")'))

    def test_single_has_full_common_output_allowance(self):
        provider = StubProvider(full_budget=True)
        result = run_architecture("single", TASK, provider, max_output_tokens=3600)
        self.assertEqual(provider.requests[0]["max_tokens"], 3600)
        self.assertEqual(result["output_tokens"], 3600)
        self.assertEqual(result["status"], "ok")

    def test_output_budget_is_shared_not_per_worker(self):
        for name in (name for name in ARCHITECTURES if not name.startswith("artifact_") and name != "contract_adaptive"):
            with self.subTest(name=name):
                provider = StubProvider(full_budget=True)
                result = run_architecture(name, TASK, provider, max_calls=4, max_output_tokens=3600)
                self.assertLessEqual(result["calls"], 4)
                self.assertLessEqual(result["output_tokens"], 3600)
                self.assertLessEqual(sum(row["max_tokens"] for row in provider.requests), 3600)
                self.assertEqual(result["status"], "ok")

    def test_private_data_never_reaches_prompts_or_public_validator(self):
        observed = []

        def validator(public_task, answer):
            self.assertNotIn("private", public_task)
            self.assertEqual(public_task["public"]["records"], ["A", "B"])
            observed.append(answer)
            return []

        for name in (name for name in ARCHITECTURES if not name.startswith("artifact_") and name != "contract_adaptive"):
            provider = StubProvider()
            run_architecture(name, TASK, provider, public_validator=validator)
            self.assertNotIn("TOP_SECRET_HIDDEN_ANSWER", json.dumps(provider.requests))
        self.assertTrue(observed)

    def test_fixed_dag_independent_workers_do_not_see_earlier_reports(self):
        provider = StubProvider(responses=['{"marker":"UNIQUE_FIRST_WORKER_REPORT"}',
                                           '{"marker":"second"}', '{"marker":"third"}',
                                           '{"selected":"A"}'])
        result = run_architecture("fixed_dag", TASK, provider)
        for request in provider.requests[1:3]:
            self.assertNotIn("UNIQUE_FIRST_WORKER_REPORT", request["prompt"])
        self.assertIn("UNIQUE_FIRST_WORKER_REPORT", provider.requests[3]["prompt"])
        self.assertEqual(result["answer"], {"selected": "A"})

    def test_blackboard_carries_feedback_but_ablation_does_not(self):
        for name, expected in [("blackboard", True), ("blackboard_no_validation", False)]:
            provider = StubProvider()
            run_architecture(name, TASK, provider,
                             public_validator=lambda task, answer: ["UNIQUE_PUBLIC_VIOLATION"])
            self.assertEqual("UNIQUE_PUBLIC_VIOLATION" in provider.requests[1]["prompt"], expected)

    def test_bazaar_filters_by_feasibility_not_hidden_correctness(self):
        provider = StubProvider(responses=['{"selected":"A"}', '{"selected":"bad"}',
                                           '{"selected":"B"}', '{"selected":"B"}'])
        result = run_architecture("bazaar", TASK, provider,
                                  public_validator=lambda task, answer:
                                  [] if answer["selected"] in task["public"]["records"] else ["unknown id"])
        event = next(row for row in result["trace"] if row.get("event") == "feasibility_filter")
        self.assertEqual(event["retained_branches"], [1, 3])
        self.assertNotIn('"selected":"bad"', provider.requests[3]["prompt"])
        self.assertIn('"selected":"A"', provider.requests[3]["prompt"])
        self.assertIn('"selected":"B"', provider.requests[3]["prompt"])

    def test_market_allocation_is_distinct_and_uncalibrated(self):
        bids = {"bids": [{"worker": "facts", "bid": 0.8, "brief": "check facts"},
                         {"worker": "facts", "bid": 0.99, "brief": "replacement bid"},
                         {"worker": "optimizer", "bid": 0.7, "brief": "optimize"},
                         {"worker": "auditor", "bid": 0.9, "brief": "audit"}]}
        provider = StubProvider(responses=[json.dumps(bids), '{}', '{}', '{"selected":"A"}'])
        result = run_architecture("market", TASK, provider)
        event = next(row for row in result["trace"] if row.get("event") == "deterministic_bid_allocation")
        self.assertEqual([row["worker"] for row in event["winners"]], ["facts", "auditor"])
        self.assertEqual(event["calibration"], "none_self_report")

    def test_adaptive_route_is_predeclared_public_family_only(self):
        for family, expected in [("sequential", "single_refine"), ("planning", "fixed_dag"),
                                 ("evidence", "blackboard"), ("unseen", "single_refine")]:
            task = dict(TASK, family=family)
            result = run_architecture("adaptive", task, StubProvider())
            self.assertEqual(result["effective_architecture"], expected)
            self.assertFalse(result["trace"][0]["uses_hidden_score"])

    def test_call_and_input_budgets_stop_incomplete_graph(self):
        provider = StubProvider()
        result = run_architecture("hierarchy", TASK, provider, max_calls=2)
        self.assertEqual(result["calls"], 2)
        self.assertEqual(result["status"], "budget_exhausted")
        provider = StubProvider()
        result = run_architecture("single", TASK, provider, max_input_tokens=1)
        self.assertEqual(result["calls"], 0)
        self.assertEqual(result["status"], "input_budget_exhausted")

    def test_unknown_provider_errors_are_sanitized_and_not_retried(self):
        provider = StubProvider(fail_at=0)
        result = run_architecture("single_refine", TASK, provider)
        self.assertEqual(result["calls"], 1)
        self.assertEqual(result["status"], "provider_error")
        self.assertFalse(result["usage_complete"])
        self.assertNotIn("credential-secret", json.dumps(result))


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.headers = {"request-id": "req-test"}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.payload


class FakeOpener:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.request = None

    def open(self, request, timeout):
        self.request = request
        if self.error:
            raise self.error
        return self.response


class ProviderTests(unittest.TestCase):
    def test_rejects_insecure_or_credential_bearing_base_urls(self):
        for url in ["http://api.example.com", "https://user:secret@api.example.com",
                    "https://api.example.com/?token=secret", "https://api.example.com/#frag"]:
            with self.assertRaises(ValueError):
                Provider(base_url=url, token="secret", model="example")
        self.assertIsNone(_NoRedirect().redirect_request(None, None, 302, "", {}, "https://evil.test"))

    def test_usage_includes_cached_input_and_excludes_thinking_text(self):
        payload = {"model": "example", "content": [
            {"type": "thinking", "thinking": "not final answer"},
            {"type": "text", "text": '{"ok":true}'}],
            "usage": {"input_tokens": 10, "cache_read_input_tokens": 30,
                      "cache_creation_input_tokens": 5, "output_tokens": 20}}
        opener = FakeOpener(FakeResponse(json.dumps(payload).encode()))
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            provider = Provider(base_url="https://example.test/anthropic", token="super-secret",
                                model="example[1m]", log_dir=directory)
            with patch("urllib.request.build_opener", return_value=opener):
                result = provider.complete("system", "prompt", max_tokens=3600)
            self.assertEqual(result["input_tokens"], 45)
            self.assertEqual(result["output_tokens"], 20)
            self.assertEqual(result["text"], '{"ok":true}')
            body = json.loads(opener.request.data)
            self.assertEqual(body["thinking"], {"type": "disabled"})
            self.assertEqual(body["max_tokens"], 3600)
            self.assertEqual(body["model"], "example")
            logs = list(Path(directory).glob("*.json"))
            self.assertEqual(len(logs), 1)
            self.assertNotIn("super-secret", logs[0].read_text(encoding="utf-8"))
            self.assertEqual(provider.totals["input_tokens"], 45)

    def test_api_error_body_is_not_echoed_and_no_retry_occurs(self):
        error = urllib.error.HTTPError("https://example.test", 401, "unauthorized", {}, None)
        opener = FakeOpener(error=error)
        provider = Provider(base_url="https://example.test", token="secret", model="example")
        with patch("urllib.request.build_opener", return_value=opener) as constructor:
            with self.assertRaises(ProviderError) as caught:
                provider.complete("system", "prompt")
        self.assertEqual(caught.exception.status, 401)
        self.assertEqual(constructor.call_count, 1)
        self.assertEqual(provider.totals["failed_attempts_with_unknown_usage"], 1)

    def test_malformed_api_json_is_explicit_failure(self):
        provider = Provider(base_url="https://example.test", token="secret", model="example")
        with patch("urllib.request.build_opener", return_value=FakeOpener(FakeResponse(b"not-json"))):
            with self.assertRaises(ProviderError) as caught:
                provider.complete("system", "prompt")
        self.assertEqual(caught.exception.code, "invalid_api_json")


if __name__ == "__main__":
    unittest.main()
