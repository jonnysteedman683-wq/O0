"""O0 capability harness (v0). Green = a promotion may be recorded."""
import hashlib
import json
import subprocess

import pytest

from o0.identity import Identity
from o0.ledger import Ledger
from o0.memory import Memory
from o0.reasoning import ReasoningLoop
from o0.research import VaultIndex, _parse_frontmatter
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
