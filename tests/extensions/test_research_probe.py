"""Tests for the research capability probe (extensions/probes/research.py)."""
from __future__ import annotations

from o0.probes import Probe, ProbeResult
from o0.research import INDEX_PATH

from extensions.probes import EXTENSION_PROBES, run_extension_probes
from extensions.probes.research import (
    CORPUS,
    KINDS,
    RESEARCH_TASKS,
    ResearchProbe,
    ResearchTask,
)

MINI_CORPUS = {
    "cats.md": "---\ntitle: Feline behaviour\ntags: [cats]\n---\nCats purr and hunt mice.\n",
    "rockets.md": "---\ntitle: Rocket propulsion\ntags: [space]\n---\nThrust from combustion.\n",
}


def test_is_probe_subclass_and_registered():
    assert issubclass(ResearchProbe, Probe)
    assert ResearchProbe.name == "research"
    assert EXTENSION_PROBES["research"] is ResearchProbe


def test_suite_is_well_formed():
    for t in RESEARCH_TASKS:
        assert t.kind in KINDS
        if t.kind == "negative":
            assert t.gold is None
        else:
            assert t.gold in CORPUS, f"gold {t.gold!r} missing from corpus"
    assert {t.kind for t in RESEARCH_TASKS} == set(KINDS)


def test_returns_real_bounded_score():
    r = ResearchProbe().run()
    assert isinstance(r, ProbeResult)
    assert r.name == "research"
    assert r.total == len(RESEARCH_TASKS)
    assert 0 <= r.passed <= r.total
    assert r.score == r.passed / r.total
    assert 0.0 <= r.score <= 1.0
    assert "error" not in r.detail


def test_deterministic_across_runs():
    a, b = ResearchProbe(), ResearchProbe()
    ra, rb = a.run(), b.run()
    assert ra.to_dict() == rb.to_dict()
    assert a.last_results == b.last_results


def test_scores_against_real_search_pass_and_fail():
    tasks = [
        ResearchTask("why do cats purr", "cats.md"),           # should pass
        ResearchTask("rocket thrust", "cats.md"),              # wrong gold -> fail
        ResearchTask("zzzz qqqq", None, "negative"),           # no hits -> pass
        ResearchTask("cats", None, "negative"),                # hits -> fail
    ]
    p = ResearchProbe(corpus=MINI_CORPUS, tasks=tasks)
    r = p.run()
    assert [x["passed"] for x in p.last_results] == [True, False, True, False]
    assert (r.passed, r.total, r.score) == (2, 4, 0.5)
    assert p.last_results[0]["rank"] == 1
    assert p.last_results[1]["rank"] is None


def test_partial_rank_counts_in_mrr_not_top1():
    corpus = {
        "a.md": "---\ntitle: alpha beta gamma\n---\nalpha beta gamma\n",
        "b.md": "---\ntitle: alpha\n---\nalpha\n",
    }
    p = ResearchProbe(corpus=corpus, tasks=[ResearchTask("alpha beta gamma", "b.md")])
    r = p.run()
    assert r.passed == 0
    assert p.last_results[0]["rank"] == 2
    assert "MRR@5 0.500" in r.detail


def test_empty_suite_is_not_measured():
    r = ResearchProbe(tasks=[]).run()
    assert r.score is None and r.total == 0


def test_never_touches_core_index_file():
    before = INDEX_PATH.stat().st_mtime_ns if INDEX_PATH.exists() else None
    ResearchProbe().run()
    after = INDEX_PATH.stat().st_mtime_ns if INDEX_PATH.exists() else None
    assert before == after


def test_error_is_reported_honestly(monkeypatch):
    import extensions.probes.research as mod

    def boom(self):
        raise RuntimeError("index exploded")

    monkeypatch.setattr(mod.VaultIndex, "index", boom)
    r = ResearchProbe().run()
    assert r.score == 0.0 and r.passed == 0
    assert "index exploded" in r.detail


def test_run_extension_probes():
    results = run_extension_probes()
    assert [r.name for r in results] == list(EXTENSION_PROBES)
