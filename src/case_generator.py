"""AI reasoning layer: given an Endpoint, ask Claude for edge/negative/boundary
test cases and return them as format-agnostic TestCase objects.
"""

import json
import os

import anthropic

from models import Endpoint, TestCase

DEFAULT_MODEL = "claude-sonnet-5-5"

CASES_TOOL = {
    "name": "submit_test_cases",
    "description": "Submit generated API test cases for this endpoint.",
    "input_schema": {
        "type": "object",
        "properties": {
            "cases": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "enum": ["edge", "negative", "boundary"],
                        },
                        "description": {"type": "string"},
                        "path_params": {"type": "object"},
                        "query_params": {"type": "object"},
                        "headers": {"type": "object"},
                        "body": {},
                        "expected_status": {"type": ["integer", "null"]},
                    },
                    "required": ["category", "description"],
                },
            }
        },
        "required": ["cases"],
    },
}


class _InvalidResponse(ValueError):
    """The model did not return a complete submit_test_cases payload."""


def _build_prompt(endpoint: Endpoint) -> str:
    return f"""You are testing this API endpoint:

Method: {endpoint.method}
Path: {endpoint.path}
Summary: {endpoint.summary or "(none)"}
Parameters: {json.dumps(endpoint.parameters, indent=2)}
Request body schema: {json.dumps(endpoint.request_body_schema, indent=2) if endpoint.request_body_schema else "(none)"}

Generate at most 15 of the most valuable EDGE, NEGATIVE, and BOUNDARY test
cases for this endpoint — prioritize diversity of failure mode over volume.
Cover things like: missing required fields, wrong types, empty strings,
extreme/boundary numeric values, malformed values (e.g. invalid email/date
formats), unexpected extra fields, injection-style strings, unicode/very long
strings, and auth/permission edge cases if headers suggest auth is involved.

Keep each "description" to one short sentence (under 15 words).

For each case, set expected_status to the HTTP status you'd expect a
well-behaved API to return (e.g. 400/422 for malformed input), or null if
you're not confident enough to assert one.

Call submit_test_cases exactly once with your results; do not answer in prose."""


def _request_cases(endpoint: Endpoint, client: anthropic.Anthropic) -> list[TestCase]:
    # Resolve at request time: the CLI loads .env after importing this module.
    model = os.environ.get("ANTHROPIC_MODEL", "").strip() or DEFAULT_MODEL
    options = {}
    if model == DEFAULT_MODEL:
        # Preserve no up-front thinking and the existing output budget. Other
        # models use their own defaults rather than receiving 5.5-only settings.
        options = {
            "thinking": {"type": "between_tools"},
            "output_config": {"effort": "high"},
        }
    response = client.messages.create(
        model=model,
        max_tokens=8192,
        tools=[CASES_TOOL],
        # Sonnet 5.5 rejects forced tool choice. Keep the schema non-strict:
        # arbitrary request dictionaries and bodies are part of the contract.
        tool_choice={"type": "auto"},
        messages=[{"role": "user", "content": _build_prompt(endpoint)}],
        **options,
    )

    if response.stop_reason == "refusal":
        print(f"[warn] {endpoint.method} {endpoint.path}: model refused — skipping this endpoint.")
        return []
    if response.stop_reason in {"max_tokens", "model_context_window_exceeded"}:
        raise _InvalidResponse(f"response stopped at {response.stop_reason}")

    tool_uses = [
        block for block in response.content
        if block.type == "tool_use" and block.name == CASES_TOOL["name"]
    ]
    if len(tool_uses) != 1:
        raise _InvalidResponse("expected one submit_test_cases tool call")
    tool_use = tool_uses[0]
    if not isinstance(tool_use.input, dict) or "cases" not in tool_use.input:
        raise _InvalidResponse("tool input must contain cases")
    raw_cases = tool_use.input["cases"]

    # The model occasionally returns the whole "cases" array (or an individual
    # case) as a JSON-encoded string instead of a real object/array, even with
    # tool use — normalize it, or raise if it's truncated/unparseable.
    if isinstance(raw_cases, str):
        raw_cases = json.loads(raw_cases)
    if not isinstance(raw_cases, list):
        raise _InvalidResponse("cases must be an array")

    cases = []
    for raw in raw_cases:
        if isinstance(raw, str):
            raw = json.loads(raw)
        if not isinstance(raw, dict) or not isinstance(raw.get("description"), str):
            raise _InvalidResponse("each case must have a description string")
        if raw.get("category") not in ("edge", "negative", "boundary"):
            raise _InvalidResponse("case category must be edge, negative, or boundary")
        for field in ("path_params", "query_params", "headers"):
            if raw.get(field) is not None and not isinstance(raw[field], dict):
                raise _InvalidResponse(f"{field} must be an object or null")
        status = raw.get("expected_status")
        if status is not None and (type(status) is not int or not 100 <= status <= 599):
            raise _InvalidResponse("expected_status must be an HTTP status code or null")
        cases.append(
            TestCase(
                endpoint=endpoint,
                category=raw["category"],
                description=raw["description"],
                path_params=raw.get("path_params") or {},
                query_params=raw.get("query_params") or {},
                headers=raw.get("headers") or {},
                body=raw.get("body"),
                expected_status=raw.get("expected_status"),
            )
        )
    return cases


def generate_cases_for_endpoint(
    endpoint: Endpoint, client: anthropic.Anthropic, max_attempts: int = 2
) -> list[TestCase]:
    for attempt in range(1, max_attempts + 1):
        try:
            return _request_cases(endpoint, client)
        except (json.JSONDecodeError, _InvalidResponse):
            if attempt == max_attempts:
                print(
                    f"[warn] {endpoint.method} {endpoint.path}: model response "
                    f"wasn't usable after {max_attempts} attempt(s) — "
                    f"skipping this endpoint."
                )
                return []
            print(
                f"[retry] {endpoint.method} {endpoint.path}: unusable "
                f"response on attempt {attempt}, retrying..."
            )


def generate_cases(endpoints: list[Endpoint]) -> list[TestCase]:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    all_cases = []
    for endpoint in endpoints:
        all_cases.extend(generate_cases_for_endpoint(endpoint, client))
    return all_cases
