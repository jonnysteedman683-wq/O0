"""O0 capability harness (v0). Green = a promotion may be recorded."""
import hashlib
import json

import pytest

from o0.identity import Identity
from o0.ledger import Ledger


@pytest.fixture(scope="module")
def identity():
    return Identity()


@pytest.fixture(scope="module")
def ledger(tmp_path_factory):
    return Ledger(tmp_path_factory.mktemp("ledger") / "test.jsonl")


def test_constitution_exists_and_hashes(identity):
    assert identity.constitution_path.exists()
    h = identity.constitution_hash
    assert len(h) == 64  # sha256 hex
    # fingerprint matches the file on disk
    expect = hashlib.sha256(identity.constitution_path.read_bytes()).hexdigest()
    assert h == expect


def test_ledger_append_and_verify(ledger):
    rec = ledger.append("test", {"a": 1})
    assert "receipt" in rec and len(rec["receipt"]) == 64
    ok, checked, broken = ledger.verify_integrity()
    assert ok is True
    assert checked == 1
    assert broken == []
    assert "seq" in rec and rec["seq"] == 1


def test_ledger_tamper_detected(ledger):
    ledger.append("test", {"b": 2})
    # corrupt a line on disk -> verification must fail
    lines = open(ledger.path, encoding="utf-8").read().splitlines()
    lines[0] = lines[0].replace('"a": 1', '"a": 999')
    open(ledger.path, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    ok, _checked, broken = ledger.verify_integrity()
    assert ok is False
    assert len(broken) >= 1


def test_identity_manifest_wellformed(identity):
    m = identity.manifest()
    assert m["name"] == "O0"
    assert m["constitution_sha256"]


def test_json_load_roundtrip(ledger):
    rec = ledger.append("test", {"x": None, "y": [1, 2]})
    re_read = json.loads(json.dumps(rec))
    assert re_read["kind"] == "test"
