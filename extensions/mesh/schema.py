"""Strict typed schemas, versioned migration, drift detection, and the wire envelope.

Every message topic and every tool input/output is described by a ``Schema``. Validation
is strict by default: unknown fields, missing required fields, wrong types (``bool`` is
never accepted where ``int`` is declared), NaN/inf, and oversized strings are all rejected.

Schema evolution is explicit: register v1 and v2, plus an upcaster v1 -> v2. A producer on
an old version keeps working (``SchemaRegistry.coerce`` migrates on receipt), and
``SchemaRegistry.drift`` reports whether a version bump is breaking before it ships.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from .clock import HLCTimestamp
from .errors import MalformedEnvelopeError, SchemaError, UnknownSchemaError
from .jsontypes import JSONObject, JSONValue, is_json_value


class Kind(StrEnum):
    STR = "str"
    INT = "int"
    FLOAT = "float"  # accepts int too (widening), never bool
    BOOL = "bool"
    STR_LIST = "str_list"
    OBJECT = "object"  # any JSON object
    JSON = "json"  # any JSON value


@dataclass(frozen=True, slots=True)
class Field:
    name: str
    kind: Kind
    required: bool = True
    nullable: bool = False
    max_len: int | None = None  # for STR / STR_LIST
    choices: tuple[str, ...] = ()

    def check(self, value: JSONValue) -> str | None:
        if value is None:
            return None if self.nullable else f"{self.name}: null not allowed"
        k = self.kind
        ok: bool
        if k is Kind.STR:
            ok = isinstance(value, str)
        elif k is Kind.INT:
            ok = isinstance(value, int) and not isinstance(value, bool)
        elif k is Kind.FLOAT:
            ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        elif k is Kind.BOOL:
            ok = isinstance(value, bool)
        elif k is Kind.STR_LIST:
            ok = isinstance(value, list) and all(isinstance(v, str) for v in value)
        elif k is Kind.OBJECT:
            ok = isinstance(value, dict)
        else:
            ok = True
        if not ok:
            return f"{self.name}: expected {k.value}, got {type(value).__name__}"
        if not is_json_value(value):
            return f"{self.name}: not a finite JSON value"
        if self.max_len is not None and isinstance(value, (str, list)) and len(value) > self.max_len:
            return f"{self.name}: length {len(value)} exceeds {self.max_len}"
        if self.choices and isinstance(value, str) and value not in self.choices:
            return f"{self.name}: {value!r} not in {list(self.choices)}"
        return None


@dataclass(frozen=True, slots=True)
class Schema:
    name: str
    version: int
    fields: tuple[Field, ...]
    allow_unknown: bool = False

    def __post_init__(self) -> None:
        names = [f.name for f in self.fields]
        if len(names) != len(set(names)):
            raise ValueError(f"schema {self.name} has duplicate field names")
        if self.version < 1:
            raise ValueError("schema versions start at 1")

    @property
    def key(self) -> str:
        return f"{self.name}@v{self.version}"

    def validate(self, payload: Mapping[str, object]) -> JSONObject:
        """Return a validated copy of ``payload`` or raise ``SchemaError``."""
        violations: list[str] = []
        if not isinstance(payload, Mapping):
            raise SchemaError(self.key, ["payload is not an object"])
        declared = {f.name: f for f in self.fields}
        out: JSONObject = {}
        for name, raw in payload.items():
            if not isinstance(name, str):
                violations.append(f"non-string key {name!r}")
                continue
            spec = declared.get(name)
            if spec is None:
                if not self.allow_unknown:
                    violations.append(f"{name}: unknown field")
                elif is_json_value(raw):
                    out[name] = _copy(raw)  # type: ignore[arg-type]
                else:
                    violations.append(f"{name}: not a JSON value")
                continue
            if not is_json_value(raw):
                violations.append(f"{name}: not a finite JSON value")
                continue
            err = spec.check(raw)  # type: ignore[arg-type]
            if err:
                violations.append(err)
            else:
                out[name] = _copy(raw)  # type: ignore[arg-type]
        for f in self.fields:
            if f.required and f.name not in payload:
                violations.append(f"{f.name}: required field missing")
        if violations:
            raise SchemaError(self.key, violations)
        return out


def _copy(v: JSONValue) -> JSONValue:
    if isinstance(v, list):
        return [_copy(x) for x in v]
    if isinstance(v, dict):
        return {k: _copy(x) for k, x in v.items()}
    return v


@dataclass(frozen=True, slots=True)
class DriftReport:
    old: str
    new: str
    added_required: tuple[str, ...] = ()
    added_optional: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    retyped: tuple[str, ...] = ()
    tightened: tuple[str, ...] = ()  # optional->required, nullable->non-null

    @property
    def breaking(self) -> bool:
        return bool(self.added_required or self.removed or self.retyped or self.tightened)


Upcaster = Callable[[JSONObject], JSONObject]


class SchemaRegistry:
    """Versioned schema store with upcasting migrations between adjacent versions."""

    def __init__(self) -> None:
        self._schemas: dict[str, dict[int, Schema]] = {}
        self._upcasters: dict[tuple[str, int], Upcaster] = {}

    def register(self, schema: Schema, *, upcast_from_previous: Upcaster | None = None) -> Schema:
        versions = self._schemas.setdefault(schema.name, {})
        if schema.version in versions and versions[schema.version] != schema:
            raise ValueError(f"{schema.key} already registered with a different shape")
        versions[schema.version] = schema
        if upcast_from_previous is not None:
            self._upcasters[(schema.name, schema.version - 1)] = upcast_from_previous
        return schema

    def get(self, name: str, version: int | None = None) -> Schema:
        versions = self._schemas.get(name)
        if not versions:
            raise UnknownSchemaError(name)
        v = max(versions) if version is None else version
        if v not in versions:
            raise UnknownSchemaError(f"{name}@v{v}")
        return versions[v]

    def latest_version(self, name: str) -> int:
        return self.get(name).version

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._schemas

    def coerce(self, name: str, version: int, payload: Mapping[str, object]) -> tuple[int, JSONObject]:
        """Validate at ``version`` then upcast step by step to the latest version."""
        current = self.get(name, version).validate(payload)
        latest = self.latest_version(name)
        v = version
        while v < latest:
            up = self._upcasters.get((name, v))
            if up is None:
                raise SchemaError(f"{name}@v{v}", [f"no upcaster to v{v + 1}"])
            v += 1
            current = self.get(name, v).validate(up(current))
        return v, current

    def drift(self, name: str, old_version: int, new_version: int) -> DriftReport:
        old, new = self.get(name, old_version), self.get(name, new_version)
        of = {f.name: f for f in old.fields}
        nf = {f.name: f for f in new.fields}
        return DriftReport(
            old=old.key,
            new=new.key,
            added_required=tuple(sorted(n for n in nf.keys() - of.keys() if nf[n].required)),
            added_optional=tuple(sorted(n for n in nf.keys() - of.keys() if not nf[n].required)),
            removed=tuple(sorted(of.keys() - nf.keys())),
            retyped=tuple(sorted(n for n in of.keys() & nf.keys() if of[n].kind != nf[n].kind)),
            tightened=tuple(
                sorted(
                    n
                    for n in of.keys() & nf.keys()
                    if (nf[n].required and not of[n].required)
                    or (of[n].nullable and not nf[n].nullable)
                )
            ),
        )


# --- wire envelope ----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Envelope:
    """The only thing that travels between actors. Immutable; payload is schema-validated
    at the receiver before any handler sees it."""

    topic: str
    schema_version: int
    sender: str
    recipient: str
    ts: HLCTimestamp
    payload: JSONObject
    msg_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    correlation_id: str | None = None
    reply_to: str | None = None
    attempt: int = 0
    deadline_ms: int | None = None

    def with_attempt(self, attempt: int) -> Envelope:
        return Envelope(
            self.topic,
            self.schema_version,
            self.sender,
            self.recipient,
            self.ts,
            self.payload,
            self.msg_id,
            self.correlation_id,
            self.reply_to,
            attempt,
            self.deadline_ms,
        )

    def to_wire(self) -> JSONObject:
        return {
            "topic": self.topic,
            "schema_version": self.schema_version,
            "sender": self.sender,
            "recipient": self.recipient,
            "ts": self.ts.encode(),
            "payload": dict(self.payload),
            "msg_id": self.msg_id,
            "correlation_id": self.correlation_id,
            "reply_to": self.reply_to,
            "attempt": self.attempt,
            "deadline_ms": self.deadline_ms,
        }

    @classmethod
    def from_wire(cls, raw: object) -> Envelope:
        try:
            WIRE.validate(raw)  # type: ignore[arg-type]
        except SchemaError as exc:
            raise MalformedEnvelopeError(str(exc)) from exc
        assert isinstance(raw, Mapping)
        payload = raw["payload"]
        assert isinstance(payload, dict)
        return cls(
            topic=str(raw["topic"]),
            schema_version=int(raw["schema_version"]),
            sender=str(raw["sender"]),
            recipient=str(raw["recipient"]),
            ts=HLCTimestamp.decode(str(raw["ts"])),
            payload=payload,
            msg_id=str(raw["msg_id"]),
            correlation_id=_opt_str(raw.get("correlation_id")),
            reply_to=_opt_str(raw.get("reply_to")),
            attempt=int(raw.get("attempt") or 0),
            deadline_ms=_opt_int(raw.get("deadline_ms")),
        )


def _opt_str(v: object) -> str | None:
    return None if v is None else str(v)


def _opt_int(v: object) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


WIRE = Schema(
    "mesh.envelope",
    1,
    (
        Field("topic", Kind.STR, max_len=128),
        Field("schema_version", Kind.INT),
        Field("sender", Kind.STR, max_len=128),
        Field("recipient", Kind.STR, max_len=128),
        Field("ts", Kind.STR, max_len=200),
        Field("payload", Kind.OBJECT),
        Field("msg_id", Kind.STR, max_len=64),
        Field("correlation_id", Kind.STR, required=False, nullable=True, max_len=64),
        Field("reply_to", Kind.STR, required=False, nullable=True, max_len=128),
        Field("attempt", Kind.INT, required=False),
        Field("deadline_ms", Kind.INT, required=False, nullable=True),
    ),
)
