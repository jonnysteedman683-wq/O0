"""Unit tests for Zero-Loss AST Context Compressor."""

from extensions.compression.ast_compressor import compress_python_source


def test_compress_python_source_removes_docstrings_and_comments():
    source = '''
"""Module docstring that should be removed."""

# Helper comment
def calculate_metric(a: int, b: int) -> int:
    """Calculate the metric between a and b."""
    # Internal operation
    return a * 2 + b

class Evaluator:
    """Class docstring."""
    def run(self):
        """Method docstring."""
        return True
'''

    result = compress_python_source(source)

    assert result.syntax_verified is True
    assert result.bytes_saved > 0
    assert result.compression_ratio < 1.0

    # Ensure docstrings and comments are gone
    assert "Module docstring" not in result.compressed_code
    assert "Calculate the metric" not in result.compressed_code
    assert "Class docstring" not in result.compressed_code
    assert "# Helper comment" not in result.compressed_code

    # Ensure code structure remains intact and functional
    assert "def calculate_metric(a: int, b: int) -> int:" in result.compressed_code
    assert "return a * 2 + b" in result.compressed_code
    assert "class Evaluator:" in result.compressed_code


def test_compress_empty_or_whitespace():
    result = compress_python_source("")
    assert result.compressed_code == ""
    assert result.syntax_verified is True
    assert result.compression_ratio == 1.0


def test_compress_syntax_error_fallback():
    broken_code = "def syntax_error( broken: : int"
    result = compress_python_source(broken_code)
    # Fails AST parsing, returns fallback original code
    assert result.syntax_verified is False
    assert result.compressed_code == broken_code
    assert result.error is not None
