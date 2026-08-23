"""AI reasoning layer: given an Endpoint, ask Claude for edge/negative/boundary
test cases and return them as format-agnostic TestCase objects.
"""

import json
import os

import anthropic

from models import Endpoint, TestCase

MODEL = "claude-sonnet-4-5"

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

Call submit_test_cases with your results."""


def _request_cases(endpoint: Endpoint, client: anthropic.Anthropic) -> list[TestCase]:
    response = client.messages.create(
        model=MODEL,
        max_tokens=8192,
        tools=[CASES_TOOL],
        tool_choice={"type": "tool", "name": "submit_test_cases"},
        messages=[{"role": "user", "content": _build_prompt(endpoint)}],
    )

    tool_use = next(block for block in response.content if block.type == "tool_use")
    raw_cases = tool_use.input["cases"]

    # The model occasionally returns the whole "cases" array (or an individual
    # case) as a JSON-encoded string instead of a real object/array, even with
    # tool_choice forced — normalize it, or raise if it's truncated/unparseable.
    if isinstance(raw_cases, str):
        raw_cases = json.loads(raw_cases)

    cases = []
    for raw in raw_cases:
        if isinstance(raw, str):
            raw = json.loads(raw)
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
        except json.JSONDecodeError:
            if attempt == max_attempts:
                print(
                    f"[warn] {endpoint.method} {endpoint.path}: model response "
                    f"wasn't parseable after {max_attempts} attempt(s) — "
                    f"skipping this endpoint."
                )
                return []
            print(
                f"[retry] {endpoint.method} {endpoint.path}: unparseable "
                f"response on attempt {attempt}, retrying..."
            )


def generate_cases(endpoints: list[Endpoint]) -> list[TestCase]:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    all_cases = []
    for endpoint in endpoints:
        all_cases.extend(generate_cases_for_endpoint(endpoint, client))
    return all_cases
