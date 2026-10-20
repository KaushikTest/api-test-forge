# api-test-forge

A CLI tool that takes an OpenAPI/Swagger spec and uses Claude to generate
edge-case, negative-case, and boundary test cases for the API — output as a
runnable pytest suite.

## How it works

```
OpenAPI spec (yaml/json)
    ↓
Spec parser (endpoints, params, request body schemas)
    ↓
AI reasoning layer (Claude generates edge/negative/boundary cases per endpoint)
    ↓
pytest suite (one test function per case, ready to run against a live base URL)
```

For each endpoint, Claude is asked to reason about how it could realistically
break — missing required fields, wrong types, boundary numeric values,
malformed formats, injection-style strings, auth edge cases — and returns a
structured set of test cases via a forced tool call, which get rendered
straight into pytest.

## Example

Run against the sample spec in `examples/petstore.yaml`:

```
python src/cli.py examples/petstore.yaml --out generated
```

A real run against that spec is committed at
[`examples/generated-output/test_generated.py`](examples/generated-output/test_generated.py)
— 30 generated test functions across the spec's endpoints, collectible and
runnable as-is with `pytest`.

## Known limitation

The model occasionally returns a malformed/truncated response for an endpoint
with a large request body schema. Rather than crash the whole run, the CLI
retries once and, if that also fails, skips just that endpoint with a printed
warning — the rest of the run completes normally. This is a real, observed
model behavior, not a hypothetical.

Generated test descriptions and paths are escaped before being written as Python.
Cases without an expected HTTP status are marked as skipped for human review;
they are not counted as passing checks. Review generated assertions before
running them against an API.

## Setup

```
python -m venv venv
source venv/Scripts/activate   # Git Bash on Windows
pip install -r requirements.txt
cp .env.example .env           # add your own ANTHROPIC_API_KEY
```

## Status

v1 — functional end-to-end for OpenAPI specs, pytest output only. Postman
output and multi-spec-version diffing are not implemented.
