# api-test-forge

A CLI tool that takes an OpenAPI/Swagger spec and uses AI to generate edge-case,
negative-case, and boundary test cases for the API — output as a runnable
pytest suite (and/or Postman collection).

## Status

Early scaffolding — weekend project, not production-ready yet.

## Planned flow

```
OpenAPI spec (yaml/json)
    ↓
Spec parser (endpoints, params, schemas, constraints)
    ↓
AI reasoning layer (generate edge/negative/boundary cases per endpoint)
    ↓
Test case generator (pytest suite output)
    ↓
Optional: run against a live base URL, report pass/fail
```

## Setup

```
python -m venv venv
source venv/Scripts/activate   # Git Bash on Windows
pip install -r requirements.txt
```
