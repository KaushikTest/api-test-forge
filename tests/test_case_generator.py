"""Offline model-migration checks: no credentials or live API calls."""

import io
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import anthropic
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import case_generator
from case_generator import CASES_TOOL, generate_cases, generate_cases_for_endpoint
from models import Endpoint, TestCase


def response(cases=None, *, content=None, stop_reason="tool_use"):
    if content is None:
        content = [SimpleNamespace(
            type="tool_use", name="submit_test_cases", input={"cases": cases},
        )]
    return SimpleNamespace(content=content, stop_reason=stop_reason)


class CaseGeneratorTests(unittest.TestCase):
    def setUp(self):
        # Replace the mapping rather than inspecting the user's environment.
        self.env = {}
        self.enterContext(patch.object(case_generator.os, "environ", self.env))
        # SDK credential discovery must use an empty directory on every OS.
        temporary_home = Path(self.enterContext(TemporaryDirectory()))
        self.enterContext(patch.object(Path, "home", return_value=temporary_home))
        self.output = self.enterContext(patch("sys.stdout", new_callable=io.StringIO))
        self.endpoint = Endpoint(
            path="/pets/{id}", method="POST", operation_id=None,
            parameters=[], request_body_schema={"type": "object"},
        )
        self.raw = {
            "category": "negative", "description": "Reject an invalid pet",
            "path_params": {"id": "bad"}, "query_params": {"unknown": [1, 2]},
            "headers": {"X-Test": "value"}, "body": {"extra": {"nested": True}},
            "expected_status": 422,
        }
        self.client = Mock()
        self.client.messages.create.return_value = response([self.raw])

    def generate(self, **kwargs):
        return generate_cases_for_endpoint(self.endpoint, self.client, **kwargs)

    def test_default_request_uses_supported_sonnet_55_parameters(self):
        self.generate()
        request = self.client.messages.create.call_args.kwargs
        self.assertEqual(request, {
            "model": "claude-sonnet-5-5",
            "max_tokens": 8192,
            "tools": [CASES_TOOL],
            "tool_choice": {"type": "auto"},
            "thinking": {"type": "between_tools"},
            "output_config": {"effort": "high"},
            "messages": [{"role": "user", "content": case_generator._build_prompt(self.endpoint)}],
        })
        self.assertNotIn("strict", request["tools"][0])
        self.assertIn("Call submit_test_cases exactly once", request["messages"][0]["content"])

    def test_override_is_trimmed_and_resolved_after_import(self):
        for model in ("claude-sonnet-4-5", "custom-model"):
            self.env["ANTHROPIC_MODEL"] = f"  {model}\n"
            self.generate()
            request = self.client.messages.create.call_args.kwargs
            self.assertEqual(request["model"], model)
            self.assertEqual(request["tool_choice"], {"type": "auto"})
            self.assertNotIn("thinking", request)
            self.assertNotIn("output_config", request)

    def test_empty_and_whitespace_model_use_default(self):
        for value in ("", " \t\n", " claude-sonnet-5-5 "):
            with self.subTest(value=value):
                self.env["ANTHROPIC_MODEL"] = value
                self.generate()
                self.assertEqual(self.client.messages.create.call_args.kwargs["model"],
                                 "claude-sonnet-5-5")

    def test_dotenv_loaded_after_import_and_shell_precedence(self):
        load_dotenv(stream=io.StringIO("ANTHROPIC_MODEL=from-dotenv\n"))
        self.generate()
        self.assertEqual(self.client.messages.create.call_args.kwargs["model"], "from-dotenv")
        self.env["ANTHROPIC_MODEL"] = "from-shell"
        load_dotenv(stream=io.StringIO("ANTHROPIC_MODEL=from-dotenv\n"))
        self.generate()
        self.assertEqual(self.client.messages.create.call_args.kwargs["model"], "from-shell")

    def test_real_sdk_constructs_default_and_legacy_requests_without_network(self):
        for model in ("claude-sonnet-5-5", "claude-sonnet-4-5"):
            with self.subTest(model=model):
                self.env["ANTHROPIC_MODEL"] = model
                # Exercise the installed SDK signature and body construction,
                # stopping before its HTTP boundary with an explicit fake key.
                with patch.object(anthropic.Anthropic, "post", return_value=response([self.raw])) as post:
                    with anthropic.Anthropic(api_key="offline-test-key", max_retries=0) as client:
                        cases = generate_cases_for_endpoint(self.endpoint, client)
                self.assertEqual(cases, [TestCase(endpoint=self.endpoint, **self.raw)])
                body = post.call_args.kwargs["body"]
                self.assertEqual(post.call_args.args[0], "/v1/messages")
                self.assertEqual(body["model"], model)
                self.assertEqual(body["tool_choice"], {"type": "auto"})
                if model == "claude-sonnet-5-5":
                    self.assertEqual(body["thinking"], {"type": "between_tools"})
                    self.assertEqual(body["output_config"], {"effort": "high"})

    def test_thinking_and_text_before_named_tool_preserve_case_contract(self):
        self.client.messages.create.return_value.content[:0] = [
            SimpleNamespace(type="thinking", thinking="", signature="opaque"),
            SimpleNamespace(type="text", text="Here are the cases."),
            SimpleNamespace(type="tool_use", name="unrelated", input={}),
        ]
        self.assertEqual(self.generate(), [TestCase(endpoint=self.endpoint, **self.raw)])

    def test_json_encoded_array_and_case_normalization_are_preserved(self):
        for payload in (json.dumps([self.raw]), [json.dumps(self.raw)]):
            with self.subTest(payload=payload):
                self.client.messages.create.return_value = response(payload)
                self.assertEqual(self.generate(), [TestCase(endpoint=self.endpoint, **self.raw)])

    def test_optional_fields_and_null_dictionaries_keep_existing_defaults(self):
        minimal = {"category": "edge", "description": "Review expected behavior"}
        for raw in (minimal, {**minimal, "path_params": None, "query_params": None, "headers": None}):
            with self.subTest(raw=raw):
                self.client.messages.create.return_value = response([raw])
                self.assertEqual(self.generate(), [TestCase(endpoint=self.endpoint, **minimal)])

    def test_arbitrary_json_bodies_and_empty_cases_remain_supported(self):
        for body in (None, False, 0, "", [1, {"extra": "field"}], {"unexpected": {}}):
            with self.subTest(body=body):
                self.client.messages.create.return_value = response([{**self.raw, "body": body}])
                self.assertEqual(self.generate()[0].body, body)
        self.client.messages.create.return_value = response([])
        self.assertEqual(self.generate(), [])

    def test_missing_tool_call_retries_once_then_succeeds(self):
        self.client.messages.create.side_effect = [
            response(content=[SimpleNamespace(type="text", text="No tool call")], stop_reason="end_turn"),
            response([self.raw]),
        ]
        self.assertEqual(len(self.generate()), 1)
        self.assertEqual(self.client.messages.create.call_count, 2)
        self.assertIn("[retry]", self.output.getvalue())

    def test_wrong_or_duplicate_tool_calls_are_bounded_and_skipped(self):
        tool = response([self.raw]).content[0]
        for content in ([], [SimpleNamespace(type="tool_use", name="wrong", input={})], [tool, tool]):
            with self.subTest(content=content):
                self.client.reset_mock()
                self.client.messages.create.return_value = response(content=content)
                self.assertEqual(self.generate(), [])
                self.assertEqual(self.client.messages.create.call_count, 2)
        self.assertIn("skipping this endpoint", self.output.getvalue())

    def test_malformed_payloads_retry_only_to_the_existing_limit(self):
        inputs = [None, {}, {"cases": None}, {"cases": {}}, {"cases": "["},
                  {"cases": ["{"]}, {"cases": [None]}, {"cases": [{}]},
                  {"cases": [{**self.raw, "category": "unknown"}]},
                  {"cases": [{**self.raw, "description": 5}]},
                  {"cases": [{**self.raw, "path_params": []}]},
                  {"cases": [{**self.raw, "query_params": "bad"}]},
                  {"cases": [{**self.raw, "headers": False}]},
                  {"cases": [{**self.raw, "expected_status": True}]},
                  {"cases": [{**self.raw, "expected_status": 999}]}]
        for payload in inputs:
            with self.subTest(payload=payload):
                self.client.reset_mock()
                self.client.messages.create.return_value = response(content=[SimpleNamespace(
                    type="tool_use", name="submit_test_cases", input=payload,
                )])
                self.assertEqual(self.generate(), [])
                self.assertEqual(self.client.messages.create.call_count, 2)

    def test_malformed_json_can_recover_on_retry(self):
        self.client.messages.create.side_effect = [response("["), response([self.raw])]
        self.assertEqual(len(self.generate()), 1)
        self.assertEqual(self.client.messages.create.call_count, 2)

    def test_truncated_responses_are_not_accepted_as_complete(self):
        for reason in ("max_tokens", "model_context_window_exceeded"):
            with self.subTest(reason=reason):
                self.client.reset_mock()
                self.client.messages.create.return_value = response([self.raw], stop_reason=reason)
                self.assertEqual(self.generate(), [])
                self.assertEqual(self.client.messages.create.call_count, 2)

    def test_refusal_is_skipped_without_retry(self):
        self.client.messages.create.return_value = response(content=[], stop_reason="refusal")
        self.assertEqual(self.generate(), [])
        self.client.messages.create.assert_called_once()
        self.assertIn("model refused", self.output.getvalue())
        self.assertNotIn("[retry]", self.output.getvalue())

    def test_explicit_retry_limit_is_respected(self):
        self.client.messages.create.return_value = response(content=[])
        self.assertEqual(self.generate(max_attempts=1), [])
        self.client.messages.create.assert_called_once()
        self.assertIn("after 1 attempt(s)", self.output.getvalue())

    def test_sdk_errors_propagate_without_application_retry(self):
        for error in (anthropic.APIError("offline API failure", Mock(), body=None), RuntimeError("transport failed")):
            with self.subTest(error=error):
                self.client.reset_mock()
                self.client.messages.create.side_effect = error
                with self.assertRaises(type(error)):
                    self.generate()
                self.client.messages.create.assert_called_once()
        self.assertNotIn("skipping", self.output.getvalue())

    def test_bad_endpoint_does_not_discard_other_endpoints(self):
        self.env["ANTHROPIC_API_KEY"] = "offline-test-key"
        self.client.messages.create.side_effect = [response(content=[]), response(content=[]), response([self.raw])]
        other = Endpoint(path="/other", method="GET", operation_id=None, parameters=[], request_body_schema=None)
        with patch.object(anthropic, "Anthropic", return_value=self.client) as factory:
            cases = generate_cases([self.endpoint, other])
        factory.assert_called_once_with(api_key="offline-test-key")
        self.assertEqual(cases, [TestCase(endpoint=other, **self.raw)])
        self.assertEqual(self.client.messages.create.call_count, 3)


if __name__ == "__main__":
    unittest.main()
