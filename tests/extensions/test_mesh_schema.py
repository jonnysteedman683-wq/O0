"""Strict schemas, version migration, drift detection, envelope wire safety."""

from __future__ import annotations

import pytest

from extensions.mesh import (
    Envelope,
    Field,
    HLCTimestamp,
    Kind,
    MalformedEnvelopeError,
    Schema,
    SchemaError,
    SchemaRegistry,
)
from extensions.mesh.errors import UnknownSchemaError

V1 = Schema("job", 1, (Field("name", Kind.STR, max_len=8), Field("n", Kind.INT)))
V2 = Schema(
    "job",
    2,
    (
        Field("name", Kind.STR, max_len=8),
        Field("count", Kind.INT),
        Field("tags", Kind.STR_LIST, required=False),
    ),
)


def test_strict_validation_catches_every_violation() -> None:
    with pytest.raises(SchemaError) as ei:
        V1.validate({"name": "much-too-long", "n": True, "extra": 1})
    v = " | ".join(ei.value.violations)
    assert "length" in v and "expected int, got bool" in v and "unknown field" in v
    with pytest.raises(SchemaError, match="required field missing"):
        V1.validate({"name": "a"})
    with pytest.raises(SchemaError, match="finite"):
        Schema("f", 1, (Field("x", Kind.FLOAT),)).validate({"x": float("nan")})


def test_validate_returns_defensive_copy() -> None:
    s = Schema("o", 1, (Field("o", Kind.OBJECT),))
    src = {"o": {"a": [1]}}
    out = s.validate(src)
    src["o"]["a"].append(2)  # type: ignore[index, union-attr]
    assert out == {"o": {"a": [1]}}


def test_float_widens_int_but_not_bool_and_choices() -> None:
    s = Schema("c", 1, (Field("x", Kind.FLOAT), Field("m", Kind.STR, choices=("a", "b"))))
    assert s.validate({"x": 3, "m": "a"}) == {"x": 3, "m": "a"}
    with pytest.raises(SchemaError):
        s.validate({"x": False, "m": "a"})
    with pytest.raises(SchemaError):
        s.validate({"x": 1.0, "m": "z"})


def test_upcasting_migrates_old_producers() -> None:
    reg = SchemaRegistry()
    reg.register(V1)
    reg.register(V2, upcast_from_previous=lambda p: {"name": p["name"], "count": p["n"]})
    version, payload = reg.coerce("job", 1, {"name": "a", "n": 4})
    assert version == 2 and payload == {"name": "a", "count": 4}


def test_missing_upcaster_is_a_schema_error() -> None:
    reg = SchemaRegistry()
    reg.register(V1)
    reg.register(V2)
    with pytest.raises(SchemaError, match="no upcaster"):
        reg.coerce("job", 1, {"name": "a", "n": 1})


def test_drift_report_flags_breaking_changes() -> None:
    reg = SchemaRegistry()
    reg.register(V1)
    reg.register(V2)
    d = reg.drift("job", 1, 2)
    assert d.breaking
    assert d.removed == ("n",) and d.added_required == ("count",) and d.added_optional == ("tags",)
    reg.register(Schema("job", 3, V2.fields + (Field("note", Kind.STR, required=False),)))
    assert not reg.drift("job", 2, 3).breaking


def test_registry_refuses_conflicting_redefinition_and_unknown() -> None:
    reg = SchemaRegistry()
    reg.register(V1)
    reg.register(V1)  # idempotent
    with pytest.raises(ValueError):
        reg.register(Schema("job", 1, (Field("other", Kind.STR),)))
    with pytest.raises(UnknownSchemaError):
        reg.get("nope")


def test_envelope_wire_roundtrip_and_malformed_rejection() -> None:
    env = Envelope("job", 1, "a", "b", HLCTimestamp(1, 2, "a"), {"name": "x", "n": 1})
    assert Envelope.from_wire(env.to_wire()) == env
    wire = env.to_wire()
    del wire["msg_id"]
    with pytest.raises(MalformedEnvelopeError):
        Envelope.from_wire(wire)
    with pytest.raises(MalformedEnvelopeError):
        Envelope.from_wire({**env.to_wire(), "payload": "garbled"})
    with pytest.raises(MalformedEnvelopeError):
        Envelope.from_wire("not even a dict")
