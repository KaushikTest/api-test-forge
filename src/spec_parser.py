"""Load and validate an OpenAPI spec, extract it into a flat list of Endpoints."""

import yaml
from openapi_spec_validator import validate

from models import Endpoint

HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


def load_spec(spec_path: str) -> dict:
    with open(spec_path, "r") as f:
        spec = yaml.safe_load(f)
    validate(spec)
    return spec


def extract_endpoints(spec: dict) -> list[Endpoint]:
    endpoints = []
    for path, path_item in spec.get("paths", {}).items():
        shared_params = path_item.get("parameters", [])
        for method, operation in path_item.items():
            if method.lower() not in HTTP_METHODS:
                continue

            params = shared_params + operation.get("parameters", [])

            request_body_schema = None
            request_body = operation.get("requestBody")
            if request_body:
                content = request_body.get("content", {})
                json_content = content.get("application/json", {})
                request_body_schema = json_content.get("schema")

            endpoints.append(
                Endpoint(
                    path=path,
                    method=method.upper(),
                    operation_id=operation.get("operationId"),
                    parameters=params,
                    request_body_schema=request_body_schema,
                    summary=operation.get("summary"),
                )
            )
    return endpoints
