"""O0 capability harness (v0). Green = a promotion may be recorded."""
import hashlib
import json
import subprocess

import pytest

from o0.agency import AgentSpec, AgentFactory, AgentRegistry, Orchestrator, StackConnector
from o0.identity import Identity
from o0.ledger import Ledger
from o0.memory import Memory
from o0.probes import (AgencyProbe, CodegenProbe, MemoryProbe, ReasoningProbe,
                       ToolUseProbe, run_all_probes)
from o0.reasoning import ReasoningLoop
from o0.research import (DEFAULT_VAULT, HORIZONTAL_ROOT, HorizontalRecall, VaultIndex,
                         running_from_horizontal,
                         _parse_frontmatter, _tokens)
from o0.selfhost import Candidate, SelfHost
from o0 import gitops


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


# -- memory ----------------------------------------------------------------

@pytest.fixture(scope="module")
def memory(tmp_path_factory):
    d = tmp_path_factory.mktemp("mem")
    return Memory(episodic_path=d / "mem.jsonl", skills_dir=d / "skills")


def test_memory_remember_and_count(memory):
    memory.remember("observation", "the flywheel promoted cleanly", tags=["flywheel"])
    memory.remember("observation", "ledger integrity held", tags=["ledger"])
    assert memory.count() == 2


def test_memory_recall_keyword(memory):
    memory.remember("observation", "constitution audit passed", tags=["constitution"])
    hits = memory.recall("constitution audit")
    assert hits and "constitution" in hits[0]["content"]


def test_memory_recall_no_match(memory):
    assert memory.recall("zzz_nonexistent_topic") == []


def test_memory_procedural_skill(memory):
    p = memory.write_skill("verify-gates", "# Verify gates\nRun pytest before promote.")
    assert p.exists()
    assert "verify-gates.md" in memory.list_skills()


# -- gitops ----------------------------------------------------------------

@pytest.fixture(scope="module")
def git_repo(tmp_path_factory):
    """A throwaway git repo with user configured, one committed file."""
    root = tmp_path_factory.mktemp("gitrepo")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "o0@test"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "O0"], check=True)
    (root / "tracked.txt").write_text("v1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "tracked.txt"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "init"], check=True)
    return root


def test_gitops_dirty_paths(git_repo):
    (git_repo / "tracked.txt").write_text("v2\n", encoding="utf-8")
    (git_repo / "new.txt").write_text("x\n", encoding="utf-8")
    dirty = gitops.dirty_paths(["tracked.txt", "new.txt", "missing.txt"], repo_root=git_repo)
    assert set(dirty) == {"tracked.txt", "new.txt"}


def test_gitops_commit_scoped(git_repo):
    # two dirty files, but commit only one -> the other stays uncommitted
    (git_repo / "tracked.txt").write_text("v3\n", encoding="utf-8")
    (git_repo / "unrelated.txt").write_text("keep me\n", encoding="utf-8")
    h = gitops.commit(["tracked.txt"], "scoped", repo_root=git_repo)
    assert h and len(h) == 40
    # unrelated file must NOT be swept in
    assert (git_repo / "unrelated.txt").exists()
    assert "unrelated.txt" in gitops.dirty_paths(["unrelated.txt"], repo_root=git_repo)


def test_gitops_commit_nothing(git_repo):
    # clean path -> returns None, no commit
    assert gitops.commit(["tracked.txt"], "noop", repo_root=git_repo) is None


# -- reasoning loop --------------------------------------------------------

class _FlakyExecutor:
    """Fails the first `fail_times` calls, then succeeds."""

    def __init__(self, fail_times: int):
        self.fail_times = fail_times
        self.calls = 0

    def execute(self, task: str) -> tuple[int, str]:
        self.calls += 1
        if self.calls <= self.fail_times:
            return 1, "boom"
        return 0, "ok"


def test_reasoning_passes_first_try(tmp_path):
    mem = Memory(episodic_path=tmp_path / "m.jsonl", skills_dir=tmp_path / "s")
    loop = ReasoningLoop(memory=mem, executor=_FlakyExecutor(0))
    r = loop.run("echo hi")
    assert r["passed"] is True
    assert r["steps"][0]["attempts"] == 1


def test_reasoning_retries_then_succeeds(tmp_path):
    # THE reflect step: a failure is not discarded, it is retried (bounded)
    mem = Memory(episodic_path=tmp_path / "m.jsonl", skills_dir=tmp_path / "s")
    loop = ReasoningLoop(memory=mem, executor=_FlakyExecutor(2), max_retries=3)
    r = loop.run("flaky task")
    assert r["passed"] is True
    assert r["steps"][0]["attempts"] == 3  # fail, fail, succeed
    # the failure lesson was stored to memory
    assert mem.count() >= 3


def test_reasoning_bounded_retries_then_fails(tmp_path):
    # never succeeds -> bounded retries, then honest failure
    mem = Memory(episodic_path=tmp_path / "m.jsonl", skills_dir=tmp_path / "s")
    loop = ReasoningLoop(memory=mem, executor=_FlakyExecutor(999), max_retries=2)
    r = loop.run("doomed task")
    assert r["passed"] is False
    assert r["steps"][0]["attempts"] == 3  # max_retries + 1


# -- research index --------------------------------------------------------

@pytest.fixture(scope="module")
def vault(tmp_path_factory):
    """A throwaway Obsidian-style vault with frontmatter notes."""
    root = tmp_path_factory.mktemp("vault")
    (root / "01_Atlas").mkdir()
    (root / "03_Sources").mkdir()
    (root / "03_Sources" / "ML_Research_Dossiers").mkdir(parents=True)
    (root / "03_Sources" / "ML_Research_Dossiers" / "a.md").write_text(
        "---\ntitle: \"Evidential Deep Learning\"\ncategory: \"cs.LG\"\n"
        "authors: \"Deep Pandey\"\nalgo_focus: \"uncertainty\"\n"
        "tags: [evidential, uncertainty]\n---\n\n"
        "## Abstract\nEvidential deep learning quantifies uncertainty. [[Related Note]]\n",
        encoding="utf-8")
    (root / "03_Sources" / "ML_Research_Dossiers" / "b.md").write_text(
        "---\ntitle: \"Modern Mathematics of Deep Learning\"\ncategory: \"cs.LG\"\n"
        "algo_focus: \"theory\"\n---\n\n## Abstract\nOverparametrized networks generalize.\n",
        encoding="utf-8")
    (root / "01_Atlas" / "c.md").write_text(
        "---\ntitle: \"Unrelated\"\n---\n\nNot ML.\n", encoding="utf-8")
    return root


def test_frontmatter_parser():
    fm = _parse_frontmatter('---\ntitle: "X"\ncategory: "cs.LG"\ntags: [a, b]\n---\nbody')
    assert fm["title"] == "X"
    assert fm["category"] == "cs.LG"
    assert fm["tags"] == ["a", "b"]


def test_tokens_stemming():
    # plural/singular recall: "superconductor" matches "superconductors"
    assert "superconductor" in _tokens("superconductors")
    assert "studies" in _tokens("studies")  # ies -> y
    assert "study" in _tokens("studies")


def test_vault_index_and_search(vault, tmp_path):
    idx = VaultIndex(vault_path=vault / "03_Sources" / "ML_Research_Dossiers",
                     index_path=tmp_path / "idx.json")
    stats = idx.index()
    assert stats["notes_indexed"] == 2  # only the ML dossiers dir
    hits = idx.search("evidential uncertainty")
    assert hits and "Evidential" in hits[0]["title"]
    assert hits[0]["wikilinks"] == ["Related Note"]


def test_vault_topics(vault, tmp_path):
    idx = VaultIndex(vault_path=vault / "03_Sources" / "ML_Research_Dossiers",
                     index_path=tmp_path / "idx2.json")
    idx.index()
    t = idx.topics()
    assert t["categories"].get("cs.LG") == 2
    assert t["algo_focus"].get("uncertainty") == 1


def test_vault_persist_reload(vault, tmp_path):
    idx = VaultIndex(vault_path=vault / "03_Sources" / "ML_Research_Dossiers",
                     index_path=tmp_path / "idx3.json")
    idx.index()
    idx2 = VaultIndex(vault_path=vault / "03_Sources" / "ML_Research_Dossiers",
                      index_path=tmp_path / "idx3.json")
    assert idx2.load() is True
    assert len(idx2.notes) == 2


def test_default_research_root_is_o0_directory():
    assert DEFAULT_VAULT == gitops.REPO_ROOT / "O0-DIRECTORY" / "O0-DIRECTORY"


def test_horizontal_runtime_detection_is_scoped_to_horizontal_root(tmp_path):
    horizontal = tmp_path / "HORIZONTAL"
    nested = horizontal / "_Meta" / "Scripts"
    outside = tmp_path / "O0"
    assert running_from_horizontal(nested, horizontal)
    assert not running_from_horizontal(outside, horizontal)


def test_vault_index_rejects_cache_for_different_root(tmp_path):
    index_file = tmp_path / "idx.json"
    index_file.write_text(json.dumps({
        "vault": str(tmp_path / "HORIZONTAL"),
        "notes": [{"title": "must not leak into O0 recall"}],
    }), encoding="utf-8")
    index = VaultIndex(vault_path=tmp_path / "O0-DIRECTORY", index_path=index_file)
    assert index.load() is False
    assert index.notes == []


def test_horizontal_recall_forwards_query_and_limit():
    calls = []

    class FakeEngine:
        def search(self, query, top_k):
            calls.append((query, top_k))
            return [{"title": "verified result"}]

    recall = HorizontalRecall(engine=FakeEngine())
    assert recall.search("agent memory", limit=4) == [{"title": "verified result"}]
    assert calls == [("agent memory", 4)]


@pytest.mark.parametrize(("query", "limit"), [("", 5), ("   ", 5), ("valid", 0)])
def test_horizontal_recall_rejects_invalid_query_or_limit(query, limit):
    with pytest.raises(ValueError):
        HorizontalRecall(engine=object()).search(query, limit=limit)


def test_horizontal_recall_cli_is_explicit(monkeypatch, capsys):
    import o0.main as main_module

    class FakeRecall:
        def search(self, query):
            assert query == "autonomous agent"
            return [{"title": "HORIZONTAL result"}]

    monkeypatch.setattr(main_module, "HorizontalRecall", FakeRecall)
    assert main_module.main(["--horizontal-recall", "autonomous agent"]) == 0
    assert json.loads(capsys.readouterr().out) == [{"title": "HORIZONTAL result"}]


@pytest.mark.parametrize("flag", ["--ml-research", "--horizontal-recall"])
def test_ml_research_flags_use_horizontal(monkeypatch, capsys, flag):
    import o0.main as main_module

    class FakeRecall:
        def search(self, query):
            assert query == "transformer architecture"
            return [{"title": "HORIZONTAL ML result"}]

    monkeypatch.setattr(main_module, "HorizontalRecall", FakeRecall)
    assert main_module.main([flag, "transformer architecture"]) == 0
    assert json.loads(capsys.readouterr().out) == [{"title": "HORIZONTAL ML result"}]


def test_local_research_cli_indexes_and_searches_o0_directory(monkeypatch, capsys):
    import o0.main as main_module

    calls = []

    class FakeIndex:
        def index(self):
            calls.append("index")

        def search(self, query):
            calls.append(("search", query))
            return [{"title": "O0 memory result"}]

    monkeypatch.setattr(main_module, "VaultIndex", FakeIndex)
    monkeypatch.setattr(main_module, "running_from_horizontal", lambda: False)
    monkeypatch.setattr(main_module, "HorizontalRecall", lambda: pytest.fail(
        "local research must not invoke HORIZONTAL"
    ))
    assert main_module.main(["--research", "MCTS topology"]) == 0
    assert calls == ["index", ("search", "MCTS topology")]
    assert json.loads(capsys.readouterr().out) == [{"title": "O0 memory result"}]


def test_research_cli_uses_horizontal_inside_horizontal_runtime(monkeypatch, capsys):
    import o0.main as main_module

    class FakeRecall:
        def search(self, query):
            assert query == "local research question"
            return [{"title": "HORIZONTAL runtime result"}]

    monkeypatch.setattr(main_module, "running_from_horizontal", lambda: True)
    monkeypatch.setattr(main_module, "HorizontalRecall", FakeRecall)
    monkeypatch.setattr(main_module, "VaultIndex", lambda: pytest.fail(
        "HORIZONTAL runtime should use HORIZONTAL recall"
    ))
    assert main_module.main(["--research", "local research question"]) == 0
    assert json.loads(capsys.readouterr().out) == [{"title": "HORIZONTAL runtime result"}]


# -- capability probes ------------------------------------------------------

def test_reasoning_probe_perfect():
    r = ReasoningProbe().run()
    assert r.score == 1.0
    assert r.passed == r.total == 5


def test_tool_use_probe_perfect():
    r = ToolUseProbe().run()
    assert r.score == 1.0
    assert r.passed == r.total


def test_memory_probe_perfect(tmp_path):
    mem = Memory(episodic_path=tmp_path / "m.jsonl", skills_dir=tmp_path / "s")
    r = MemoryProbe(memory=mem).run()
    assert r.score == 1.0
    assert r.passed == r.total == 4


def test_codegen_probe_not_measured():
    # no executor -> honest "not measured", not a fake score
    r = CodegenProbe().run()
    assert r.score is None
    assert "not measured" in r.detail


def test_codegen_probe_with_executor():
    r = CodegenProbe(codegen_fn=lambda spec: "print(40+2)").run()
    assert r.score == 1.0


def test_run_all_probes(tmp_path):
    mem = Memory(episodic_path=tmp_path / "m.jsonl", skills_dir=tmp_path / "s")
    results = run_all_probes(memory=mem)
    names = {p.name for p in results}
    assert names == {"reasoning", "tool_use", "memory", "codegen", "agency"}
    # measured probes score 1.0; codegen is None
    assert all(p.score == 1.0 for p in results if p.name != "codegen")
    assert next(p for p in results if p.name == "codegen").score is None


# -- agency (O0 creates + controls AIs) ------------------------------------

@pytest.fixture(scope="module")
def agency(tmp_path_factory):
    d = tmp_path_factory.mktemp("agency")
    ledger = Ledger(d / "ledger.jsonl")
    agents_dir = d / "agents"
    return Orchestrator(ledger=ledger, agents_dir=agents_dir)


def test_agent_factory_creates_and_registers(agency):
    agent = agency.create_agent(AgentSpec(name="scout", role="recon"))
    assert agent.module_path.exists()
    # registered in the ledger as an agent_created record
    recs = agency.factory.ledger.read()
    assert any(r["kind"] == "agent_created" and r["agent"] == "scout" for r in recs)


def test_agent_registry_lists_and_loads(agency):
    agency.create_agent(AgentSpec(name="worker", role="executor"))
    names = [a["name"] for a in agency.registry.list()]
    assert "worker" in names
    assert agency.registry.load("worker") is not None
    assert agency.registry.load("nope") is None


def test_orchestrator_dispatch(agency):
    agency.create_agent(AgentSpec(name="runner", role="task"))
    res = agency.dispatch("runner", "echo hello")
    assert res["ok"] is True
    assert res["result"]["passed"] is True


def test_stack_connector_fail_open(tmp_path):
    # reachable platform
    c = StackConnector("HORIZONTAL", "C:/Users/jonny/OneDrive/Desktop/HORIZONTAL")
    assert c.status()["reachable"] is True
    # missing platform -> fail-open, not an error
    c2 = StackConnector("MISSING", str(tmp_path / "nope"))
    assert c2.status()["reachable"] is False
    assert c2.dispatch("x")["ok"] is False


def test_agency_probe(tmp_path):
    r = AgencyProbe(agents_dir=tmp_path / "agents").run()
    assert r.score == 1.0
    assert "created agent" in r.detail


# -- self-hosting (v5) ------------------------------------------------------

def _fake_scorer(scratch_score: float, scratch_ok: bool = True):
    """A scorer that returns `scratch_score` for a scratch copy, baseline 4.0."""
    def scorer(root):
        if str(root).endswith("o0") and "tmp" in str(root):
            return {"score": scratch_score, "harness_ok": scratch_ok,
                    "compile_ok": True, "probe_score": scratch_score - 2.0}
        return {"score": 4.0, "harness_ok": True, "compile_ok": True,
                "probe_score": 2.0}
    return scorer


def test_selfhost_promotes_improvement(tmp_path):
    ledger = Ledger(tmp_path / "ledger.jsonl")
    sh = SelfHost(ledger=ledger, commit=False,
                  scorer=_fake_scorer(scratch_score=5.0))
    cand = Candidate(name="improve", target="o0/verify.py",
                     old="def capability_score", new="def capability_score_improved")
    r = sh.run(cand)
    assert r["outcome"] == "promote"
    assert r["candidate_score"] > r["baseline_score"]
    # recorded in ledger
    assert any(x["kind"] == "promote" and x["candidate"] == "improve"
               for x in ledger.read())


def test_selfhost_rejects_regression(tmp_path):
    ledger = Ledger(tmp_path / "ledger.jsonl")
    sh = SelfHost(ledger=ledger, commit=False,
                  scorer=_fake_scorer(scratch_score=3.0))
    cand = Candidate(name="regress", target="o0/verify.py",
                     old="def capability_score", new="def capability_score_bad")
    r = sh.run(cand)
    assert r["outcome"] == "reject"
    assert any(x["kind"] == "reject" and x["candidate"] == "regress"
               for x in ledger.read())


def test_selfhost_rejects_missing_target(tmp_path):
    ledger = Ledger(tmp_path / "ledger.jsonl")
    sh = SelfHost(ledger=ledger, commit=False, scorer=_fake_scorer(5.0))
    cand = Candidate(name="ghost", target="o0/nope.py",
                     old="x", new="y")
    r = sh.run(cand)
    assert r["outcome"] == "reject"
    assert "target missing" in r["reason"]


def test_selfhost_rejects_old_not_found(tmp_path):
    ledger = Ledger(tmp_path / "ledger.jsonl")
    sh = SelfHost(ledger=ledger, commit=False, scorer=_fake_scorer(5.0))
    cand = Candidate(name="nomatch", target="o0/verify.py",
                     old="this text does not exist anywhere", new="y")
    r = sh.run(cand)
    assert r["outcome"] == "reject"
    assert "old text not found" in r["reason"]
