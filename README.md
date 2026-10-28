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
structured set of test cases via the `submit_test_cases` tool, which get rendered
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

The model may omit the tool call or return malformed/truncated test cases,
especially with a large request body schema. The CLI retries once and, if that
also fails, skips just that endpoint with a printed warning. Explicit model
refusals are skipped without retry; API/authentication errors still propagate.
Skipped endpoints mean incomplete coverage, not passing tests.

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

## Model configuration

`ANTHROPIC_MODEL` selects the Claude API model. Unset, empty, or whitespace-only
values use `claude-sonnet-5-5`; surrounding whitespace is trimmed. It is read at
request time, so both `.env` and shell environment values work (the shell wins).

This replaces the deprecated Sonnet 4.5 alias, which does not auto-upgrade and is
[scheduled to retire November 30, 2026](https://platform.claude.com/docs/en/about-claude/model-deprecations#2026-09-30-claude-sonnet-45-model).
The [Sonnet 5.5 migration guide](https://platform.claude.com/docs/en/models/sonnet-5-5/migration-guide)
requires automatic rather than forced tool choice. The tool remains non-strict
to preserve arbitrary parameter names and JSON bodies, including deliberately
invalid API inputs: [strict schemas forbid additional object properties](https://platform.claude.com/docs/en/build-with-claude/structured-outputs#json-schema-limitations).

For Sonnet 5.5, requests explicitly use `thinking: between_tools` and `high`
effort, preserving no up-front thinking and the existing 8,192-token ceiling.
Install the updated requirements (`anthropic>=1.9.0`) before running. Overrides
use automatic tool choice and their model's native thinking/effort defaults;
they do not receive Sonnet 5.5-only controls. This permits legacy-model request
shapes, but availability and compatibility of any override must be checked.
There is no automatic model fallback or increase to the token budget.

## Offline checks

```
python -m unittest discover -s tests -v
python -m py_compile src/*.py src/writers/*.py
python -m pytest examples/generated-output/test_generated.py --collect-only -q
```

Generator regression tests mock the SDK/network boundary and require no API key.
They verify configuration, request construction, response normalization, and
bounded retry/skip behavior, not live model access or output quality. Before
rollout, separately authorize a small live evaluation of coverage, assertions,
latency, and token usage; the existing example output has not been regenerated.

## Status

v1 — functional end-to-end for OpenAPI specs, pytest output only. Postman
output and multi-spec-version diffing are not implemented.
