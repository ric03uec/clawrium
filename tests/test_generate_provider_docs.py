"""Tests for the generate_provider_docs script."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# Import the functions from the script
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from generate_provider_docs import (
    format_context_window,
    generate_model_table,
    load_catalog,
    update_doc_file,
    process_provider,
    START_MARKER,
    END_MARKER,
)


class TestFormatContextWindow:
    """Tests for format_context_window function."""

    def test_format_million_tokens(self):
        """Context window >= 1M should display as M."""
        assert format_context_window(1_000_000) == "1M"
        assert format_context_window(2_000_000) == "2M"
        assert format_context_window(1_048_000) == "1M"

    def test_format_thousand_tokens(self):
        """Context window 1K-999K should display as K."""
        assert format_context_window(1000) == "1K"
        assert format_context_window(128_000) == "128K"
        assert format_context_window(999_000) == "999K"

    def test_format_small_tokens(self):
        """Context window < 1K should display as number."""
        assert format_context_window(500) == "500"
        assert format_context_window(1) == "1"
        assert format_context_window(999) == "999"

    def test_format_zero(self):
        """Context window of 0 should display as dash."""
        assert format_context_window(0) == "-"

    def test_format_negative(self):
        """Negative context window should display as dash."""
        assert format_context_window(-100) == "-"


class TestGenerateModelTable:
    """Tests for generate_model_table function."""

    def test_empty_models_ollama(self):
        """Empty models list for ollama should show dynamic discovery message."""
        result = generate_model_table([], "ollama")
        assert "discovered dynamically" in result

    def test_empty_models_other_provider(self):
        """Empty models list for other providers should show no models message."""
        result = generate_model_table([], "openai")
        assert "No models available" in result

    def test_single_lab_no_header(self):
        """Single lab should not include lab header."""
        models = [
            {"id": "gpt-4", "name": "GPT-4", "lab": "OpenAI", "context_window": 8000},
            {
                "id": "gpt-4o",
                "name": "GPT-4o",
                "lab": "OpenAI",
                "context_window": 128000,
            },
        ]
        result = generate_model_table(models, "openai")
        assert "### OpenAI" not in result
        assert "gpt-4" in result
        assert "gpt-4o" in result

    def test_multiple_labs_with_headers(self):
        """Multiple labs should include lab headers."""
        models = [
            {
                "id": "claude-3",
                "name": "Claude 3",
                "lab": "Anthropic",
                "context_window": 200000,
            },
            {"id": "gpt-4", "name": "GPT-4", "lab": "OpenAI", "context_window": 8000},
        ]
        result = generate_model_table(models, "openrouter")
        assert "### Anthropic" in result
        assert "### OpenAI" in result

    def test_model_table_format(self):
        """Model table should have correct markdown format."""
        models = [
            {"id": "gpt-4", "name": "GPT-4", "lab": "OpenAI", "context_window": 8000},
        ]
        result = generate_model_table(models, "openai")
        assert "| Model ID | Name | Context |" in result
        assert "|----------|------|---------|" in result
        assert "| `gpt-4` | GPT-4 | 8K |" in result

    def test_context_window_formatting_in_table(self):
        """Context window should be formatted correctly in table."""
        models = [
            {
                "id": "model-m",
                "name": "Model M",
                "lab": "Test",
                "context_window": 1_000_000,
            },
            {
                "id": "model-k",
                "name": "Model K",
                "lab": "Test",
                "context_window": 128_000,
            },
        ]
        result = generate_model_table(models, "test")
        assert "| 1M |" in result
        assert "| 128K |" in result

    def test_models_sorted_by_name(self):
        """Models should be sorted by name within each lab."""
        models = [
            {
                "id": "z-model",
                "name": "Zebra Model",
                "lab": "Test",
                "context_window": 1000,
            },
            {
                "id": "a-model",
                "name": "Alpha Model",
                "lab": "Test",
                "context_window": 1000,
            },
        ]
        result = generate_model_table(models, "test")
        # Alpha should appear before Zebra
        alpha_pos = result.find("Alpha Model")
        zebra_pos = result.find("Zebra Model")
        assert alpha_pos < zebra_pos


class TestUpdateDocFile:
    """Tests for update_doc_file function."""

    def test_update_replaces_content(self):
        """Content between markers should be replaced."""
        with tempfile.TemporaryDirectory() as tmpdir:
            doc_path = Path(tmpdir) / "test.md"
            doc_path.write_text(
                f"# Title\n\n{START_MARKER}\nOld content\n{END_MARKER}\n\n## Footer"
            )

            result = update_doc_file(doc_path, "New content\n")

            assert result is True
            content = doc_path.read_text()
            assert "New content" in content
            assert "Old content" not in content
            assert "# Title" in content
            assert "## Footer" in content

    def test_update_missing_markers(self):
        """Should return False if markers not found."""
        with tempfile.TemporaryDirectory() as tmpdir:
            doc_path = Path(tmpdir) / "test.md"
            doc_path.write_text("# Title\n\nNo markers here\n")

            result = update_doc_file(doc_path, "New content\n")

            assert result is False
            assert "No markers here" in doc_path.read_text()

    def test_update_file_not_found(self):
        """Should return False if file doesn't exist."""
        result = update_doc_file(Path("/nonexistent/file.md"), "content")
        assert result is False

    def test_update_idempotent(self):
        """Running update twice with same content should produce same result."""
        with tempfile.TemporaryDirectory() as tmpdir:
            doc_path = Path(tmpdir) / "test.md"
            doc_path.write_text(f"# Title\n\n{START_MARKER}\n{END_MARKER}\n")

            table_content = "| Model | Name | Context |\n|-------|------|---------|"

            update_doc_file(doc_path, table_content)
            content1 = doc_path.read_text()

            update_doc_file(doc_path, table_content)
            content2 = doc_path.read_text()

            assert content1 == content2


class TestProcessProvider:
    """Tests for process_provider function."""

    def test_process_provider_success(self):
        """Should successfully process provider with valid doc file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = Path(tmpdir)
            doc_file = docs_dir / "openai.md"
            doc_file.write_text(f"# OpenAI\n\n{START_MARKER}\n{END_MARKER}\n")

            models = [
                {
                    "id": "gpt-4",
                    "name": "GPT-4",
                    "lab": "OpenAI",
                    "context_window": 8000,
                }
            ]
            success, message = process_provider("openai", models, docs_dir)

            assert success is True
            assert "Updated" in message

    def test_process_provider_doc_not_found(self):
        """Should return False if doc file doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = Path(tmpdir)

            success, message = process_provider("openai", [], docs_dir)

            assert success is False
            assert "not found" in message

    def test_process_provider_no_markers(self):
        """Should return False if markers not in doc file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = Path(tmpdir)
            doc_file = docs_dir / "openai.md"
            doc_file.write_text("# OpenAI\n\nNo markers\n")

            success, message = process_provider("openai", [], docs_dir)

            assert success is False
            assert "No markers" in message

    def test_process_provider_dry_run(self):
        """Dry run should not modify files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = Path(tmpdir)
            doc_file = docs_dir / "openai.md"
            original_content = f"# OpenAI\n\n{START_MARKER}\nOriginal\n{END_MARKER}\n"
            doc_file.write_text(original_content)

            models = [
                {
                    "id": "gpt-4",
                    "name": "GPT-4",
                    "lab": "OpenAI",
                    "context_window": 8000,
                }
            ]
            success, message = process_provider(
                "openai", models, docs_dir, dry_run=True
            )

            assert success is True
            assert "Would update" in message
            assert doc_file.read_text() == original_content


class TestLoadCatalog:
    """Tests for load_catalog function."""

    def test_load_catalog_missing_file(self):
        """Should exit with error if catalog file doesn't exist."""
        with patch(
            "generate_provider_docs.MODELS_JSON", Path("/nonexistent/models.json")
        ):
            with pytest.raises(SystemExit) as exc_info:
                load_catalog()
            assert exc_info.value.code == 1

    def test_load_catalog_success(self):
        """Should load catalog from real models.json."""
        # This tests against the actual file
        catalog = load_catalog()
        assert "providers" in catalog
        assert "version" in catalog
