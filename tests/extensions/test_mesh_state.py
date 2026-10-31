"""HLC + CRDT laws: ordering, drift rejection, and convergence under arbitrary delivery."""

from __future__ import annotations

import itertools
import random

import pytest

from extensions.mesh import (
    ClockDriftError,
    GCounter,
    HLCTimestamp,
    HybridLogicalClock,
    LWWMap,
    MalformedEnvelopeError,
    PNCounter,
    StateDelta,
    StateReplica,
)


class FakeTime:
    def __init__(self, t: int = 1_000) -> None:
        self.t = t

    def __call__(self) -> int:
        return self.t


def test_hlc_monotonic_even_when_physical_clock_stalls_or_regresses() -> None:
    ft = FakeTime()
    c = HybridLogicalClock("a", physical_ms=ft)
    seen = [c.now() for _ in range(5)]
    ft.t = 500  # wall clock jumps backwards
    seen += [c.now() for _ in range(5)]
    assert seen == sorted(seen) and len(set(seen)) == len(seen)


def test_hlc_receive_is_after_both_local_and_remote() -> None:
    ft = FakeTime(1_000)
    a = HybridLogicalClock("a", physical_ms=ft)
    b = HybridLogicalClock("b", physical_ms=FakeTime(1_000 + 50))
    remote = b.now()
    local_before = a.now()
    merged = a.update(remote)
    assert merged > remote and merged > local_before
    assert a.now() > merged


def test_hlc_rejects_remote_far_in_future() -> None:
    a = HybridLogicalClock("a", physical_ms=FakeTime(0), max_drift_ms=100)
    with pytest.raises(ClockDriftError):
        a.update(HLCTimestamp(10_000, 0, "evil"))
    assert a.peek().wall_ms == 0  # the bad timestamp did not poison local time


def test_hlc_encode_roundtrip_and_malformed() -> None:
    ts = HLCTimestamp(123, 4, "node-x")
    assert HLCTimestamp.decode(ts.encode()) == ts
    for bad in ("", "1.2", "x.y.z", "1.2."):
        with pytest.raises(MalformedEnvelopeError):
            HLCTimestamp.decode(bad)


def test_hlc_node_id_validation() -> None:
    with pytest.raises(ValueError):
        HybridLogicalClock("a.b")


def _rand_gcounter(rng: random.Random) -> GCounter:
    return GCounter({f"n{i}": rng.randint(0, 9) for i in range(rng.randint(0, 4))})


def test_gcounter_merge_is_a_semilattice() -> None:
    rng = random.Random(1)
    for _ in range(200):
        a, b, c = (_rand_gcounter(rng) for _ in range(3))
        assert a.merge(b) == b.merge(a)
        assert a.merge(b).merge(c) == a.merge(b.merge(c))
        assert a.merge(a) == a
        assert a.merge(b).value >= max(a.value, b.value)
    with pytest.raises(ValueError):
        GCounter().increment("n", -1)


def test_pncounter_converges_across_replicas() -> None:
    a, b = PNCounter(), PNCounter()
    a.increment("a", 5)
    b.decrement("b", 2)
    a.decrement("a", 1)
    assert a.merge(b).value == b.merge(a).value == 2


def _rand_map(rng: random.Random, node: str) -> LWWMap:
    m = LWWMap()
    for i in range(rng.randint(0, 6)):
        ts = HLCTimestamp(rng.randint(0, 5), rng.randint(0, 3), node)
        k = f"k{rng.randint(0, 3)}"
        if rng.random() < 0.3:
            m.delete(k, ts)
        else:
            m.set(k, i, ts)
    return m


def test_lwwmap_merge_is_a_semilattice() -> None:
    rng = random.Random(2)
    for _ in range(200):
        a, b, c = _rand_map(rng, "a"), _rand_map(rng, "b"), _rand_map(rng, "c")
        assert a.merge(b) == b.merge(a)
        assert a.merge(b).merge(c) == a.merge(b.merge(c))
        assert a.merge(a) == a


def test_tombstone_beats_stale_write() -> None:
    m = LWWMap()
    m.set("k", "v1", HLCTimestamp(1, 0, "a"))
    m.delete("k", HLCTimestamp(3, 0, "b"))
    assert not m.set("k", "stale", HLCTimestamp(2, 0, "c"))
    assert "k" not in m and m.get("k") is None


def test_replicas_converge_under_any_order_with_duplicates() -> None:
    ft = FakeTime()
    writers = [StateReplica(HybridLogicalClock(f"w{i}", physical_ms=ft)) for i in range(3)]
    deltas: list[StateDelta] = []
    for w in writers:
        w.subscribe(deltas.append)
    rng = random.Random(3)
    for step in range(60):
        ft.t += rng.choice([0, 0, 1])  # lots of same-millisecond writes
        w = rng.choice(writers)
        k = f"k{rng.randint(0, 4)}"
        if rng.random() < 0.2:
            w.delete(k)
        else:
            w.set(k, step)
    stream = deltas + rng.sample(deltas, 20)  # duplicates
    finals = []
    for perm_seed in range(5):
        r = StateReplica(HybridLogicalClock("reader", physical_ms=ft))
        order = stream[:]
        random.Random(perm_seed).shuffle(order)
        for d in order:
            r.apply(d)
        finals.append(r.snapshot())
    assert all(f == finals[0] for f in finals)


def test_delta_wire_roundtrip_and_validation() -> None:
    d = StateDelta("k", {"x": [1, 2]}, False, HLCTimestamp(9, 1, "n"))
    assert StateDelta.from_wire(d.to_wire()) == d
    with pytest.raises(MalformedEnvelopeError):
        StateDelta.from_wire({"key": 1, "deleted": False, "ts": "x"})


def test_merge_from_repairs_divergent_replicas() -> None:
    ft = FakeTime()
    a = StateReplica(HybridLogicalClock("a", physical_ms=ft))
    b = StateReplica(HybridLogicalClock("b", physical_ms=ft))
    a.set("x", 1)
    b.set("y", 2)
    b.delete("x")  # b never saw a's write; LWW still resolves deterministically
    for r1, r2 in itertools.permutations([a, b]):
        r1.merge_from(r2.state)
    assert a.state == b.state
