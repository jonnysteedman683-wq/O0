"""Shared type aliases for the mesh engine.

Every payload that crosses an actor, tool, or transport boundary is a ``JSONObject``: a plain,
JSON-serialisable mapping. Keeping the wire type this narrow is what makes schema validation,
deduplication by content hash, and process isolation possible without pickling.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import TypeAlias, Union

JSONScalar: TypeAlias = Union[None, bool, int, float, str]
JSONValue: TypeAlias = Union[JSONScalar, list["JSONValue"], dict[str, "JSONValue"]]
JSONObject: TypeAlias = dict[str, JSONValue]


def canonical_json(value: JSONValue | Mapping[str, JSONValue]) -> str:
    """Deterministic encoding (sorted keys, no whitespace) used for hashing and dedup."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def is_json_value(value: object, *, _depth: int = 0) -> bool:
    """True when ``value`` is a finite, JSON-representable tree (bounded depth)."""
    if _depth > 64:
        return False
    if value is None or isinstance(value, (bool, int, str)):
        return True
    if isinstance(value, float):
        return value == value and value not in (float("inf"), float("-inf"))
    if isinstance(value, list):
        return all(is_json_value(v, _depth=_depth + 1) for v in value)
    if isinstance(value, dict):
        return all(
            isinstance(k, str) and is_json_value(v, _depth=_depth + 1) for k, v in value.items()
        )
    return False
