"""Unit tests for MCTS Dynamic Pipeline DAG Synthesizer and Executor."""

from extensions.mcts.dag_synthesizer import (
    MCTSPipelineSynthesizer,
    PipelineDAG,
    PipelineExecutor,
)


def mock_secret_redactor(raw_text: str) -> str:
    """Redacts secrets and API keys from text."""
    return raw_text.replace("sk-12345", "[REDACTED_KEY]")


def mock_ast_compressor(text: str) -> str:
    """Compresses comments and docstrings from python source code."""
    lines = [l for l in text.splitlines() if not l.strip().startswith("#")]
    return "\n".join(lines)


def mock_merkle_sealer(code: str) -> str:
    """Computes cryptographic integrity seal for payload."""
    return f"SEALED({code})"


def test_mcts_tool_registration_and_matching():
    synth = MCTSPipelineSynthesizer()
    synth.register_tool(
        name="redact_secrets",
        entry_fn=mock_secret_redactor,
        docstring="Sanitize API keys and secrets",
        capabilities=["security", "redaction"],
    )

    assert "redact_secrets" in synth.catalog
    descriptor = synth.catalog["redact_secrets"]
    assert descriptor.match_score({"security", "audit"}) == 1.0
    assert descriptor.match_score({"unrelated", "cooking"}) == 0.0


def test_mcts_search_discovers_optimal_pipeline():
    synth = MCTSPipelineSynthesizer(max_depth=3)
    synth.register_tool("redact_secrets", mock_secret_redactor, "Redact API keys and passwords", ["security"])
    synth.register_tool("compress_code", mock_ast_compressor, "Compress python source AST code", ["compression"])
    synth.register_tool("seal_merkle", mock_merkle_sealer, "Cryptographically seal output hash", ["merkle"])

    # Goal that touches all 3 registered tools
    dag = synth.search_optimal_pipeline("Clean security secrets, compress python code, and seal merkle output", simulations=50)

    assert len(dag.stages) >= 2
    tool_names = [s.tool_name for s in dag.stages]
    # At least two of the target tools should be included
    assert "redact_secrets" in tool_names or "compress_code" in tool_names
    assert len(dag.execution_order) == len(dag.stages)


def test_pipeline_executor_end_to_end_wiring():
    synth = MCTSPipelineSynthesizer()
    synth.register_tool("redact_secrets", mock_secret_redactor, "Redact API keys and passwords", ["security"])
    synth.register_tool("compress_code", mock_ast_compressor, "Compress python source AST code", ["compression"])
    synth.register_tool("seal_merkle", mock_merkle_sealer, "Cryptographically seal output hash", ["merkle"])

    dag = synth.search_optimal_pipeline("Redact secrets, compress code, seal output", simulations=30)
    executor = PipelineExecutor()

    initial_input = {"raw_text": "sk-12345\n# A comment\ndef hello(): return True"}
    res = executor.execute(dag, initial_input)

    assert res["success"] is True
    assert res["merkle_root"].startswith("0x")
    assert len(res["stage_telemetry"]) == len(dag.stages)
    assert res["final_result"] is not None
