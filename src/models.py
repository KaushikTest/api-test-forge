"""Format-agnostic data shapes shared by the generator and all writers."""

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Endpoint:
    path: str
    method: str
    operation_id: Optional[str]
    parameters: list[dict]        # OpenAPI parameter objects (query/path/header)
    request_body_schema: Optional[dict]
    summary: Optional[str] = None


@dataclass
class TestCase:
    endpoint: Endpoint
    category: str                  # "edge" | "negative" | "boundary"
    description: str               # why this case matters, e.g. "empty string for required field"
    path_params: dict = field(default_factory=dict)
    query_params: dict = field(default_factory=dict)
    headers: dict = field(default_factory=dict)
    body: Optional[Any] = None
    expected_status: Optional[int] = None   # None if not asserting a specific status
