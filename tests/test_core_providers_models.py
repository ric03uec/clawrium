"""Tests for model catalog module."""

import pytest
from unittest.mock import patch, mock_open

from clawrium.core.providers import (
    CatalogLoadError,
    ProviderNotFoundError,
    get_catalog_providers,
    get_model_count,
    get_model_ids_for_provider,
    get_models_for_provider,
    load_model_catalog,
    search_models,
    validate_model_id,
)


@pytest.fixture(autouse=True)
def clear_catalog_cache():
    """Clear the LRU cache before each test."""
    load_model_catalog.cache_clear()
    yield
    load_model_catalog.cache_clear()


class TestLoadModelCatalog:
    """Tests for load_model_catalog function."""

    def test_load_model_catalog_returns_dict(self):
        """load_model_catalog returns a dictionary with expected structure."""
        catalog = load_model_catalog()
        assert isinstance(catalog, dict)
        assert "version" in catalog
        assert "providers" in catalog
        assert isinstance(catalog["providers"], dict)

    def test_load_model_catalog_has_all_providers(self):
        """load_model_catalog includes all expected providers."""
        catalog = load_model_catalog()
        expected_providers = [
            "openai",
            "anthropic",
            "openrouter",
            "bedrock",
            "vertex",
            "zai",
            "ollama",
        ]
        for provider in expected_providers:
            assert provider in catalog["providers"]

    def test_load_model_catalog_caches_result(self):
        """load_model_catalog uses LRU cache."""
        # First call
        catalog1 = load_model_catalog()
        # Second call should return cached result
        catalog2 = load_model_catalog()
        assert catalog1 is catalog2

    def test_load_model_catalog_file_not_found(self):
        """load_model_catalog raises CatalogLoadError when file missing."""
        with patch(
            "clawrium.core.providers.models.CATALOG_FILE", "/nonexistent/path.json"
        ):
            load_model_catalog.cache_clear()
            with pytest.raises(CatalogLoadError) as exc_info:
                load_model_catalog()
            assert "not found" in str(exc_info.value).lower()

    def test_load_model_catalog_invalid_json(self):
        """load_model_catalog raises CatalogLoadError for malformed JSON."""
        with patch("builtins.open", mock_open(read_data="not valid json {")):
            load_model_catalog.cache_clear()
            with pytest.raises(CatalogLoadError) as exc_info:
                load_model_catalog()
            assert "malformed" in str(exc_info.value).lower()


class TestGetModelsForProvider:
    """Tests for get_models_for_provider function."""

    def test_get_models_for_provider_openai(self):
        """get_models_for_provider returns models for OpenAI."""
        models = get_models_for_provider("openai")
        assert isinstance(models, list)
        assert len(models) > 0
        # Check model structure
        model = models[0]
        assert "id" in model
        assert "name" in model
        assert "lab" in model
        assert "context_window" in model
        assert "tags" in model

    def test_get_models_for_provider_anthropic(self):
        """get_models_for_provider returns models for Anthropic."""
        models = get_models_for_provider("anthropic")
        assert len(models) > 0
        model_ids = [m["id"] for m in models]
        # Check for known Claude models
        assert any("claude" in mid for mid in model_ids)

    def test_get_models_for_provider_unknown_raises(self):
        """get_models_for_provider raises ProviderNotFoundError for unknown provider."""
        with pytest.raises(ProviderNotFoundError) as exc_info:
            get_models_for_provider("unknown-provider")
        assert "unknown-provider" in str(exc_info.value)
        assert "valid providers" in str(exc_info.value).lower()

    def test_get_models_for_provider_ollama_empty(self):
        """get_models_for_provider returns empty list for ollama."""
        models = get_models_for_provider("ollama")
        assert models == []


class TestGetModelIdsForProvider:
    """Tests for get_model_ids_for_provider function."""

    def test_get_model_ids_for_provider_returns_strings(self):
        """get_model_ids_for_provider returns list of string IDs."""
        model_ids = get_model_ids_for_provider("openai")
        assert isinstance(model_ids, list)
        assert all(isinstance(mid, str) for mid in model_ids)

    def test_get_model_ids_for_provider_includes_known_models(self):
        """get_model_ids_for_provider includes expected model IDs."""
        model_ids = get_model_ids_for_provider("openai")
        assert "gpt-4o" in model_ids
        assert "gpt-4o-mini" in model_ids

    def test_get_model_ids_for_provider_unknown_raises(self):
        """get_model_ids_for_provider raises for unknown provider."""
        with pytest.raises(ProviderNotFoundError):
            get_model_ids_for_provider("nonexistent")


class TestValidateModelId:
    """Tests for validate_model_id function."""

    def test_validate_model_id_valid(self):
        """validate_model_id returns True for valid model ID."""
        assert validate_model_id("openai", "gpt-4o") is True
        assert validate_model_id("anthropic", "claude-opus-4-7") is True

    def test_validate_model_id_invalid(self):
        """validate_model_id returns False for invalid model ID."""
        assert validate_model_id("openai", "nonexistent-model") is False
        assert validate_model_id("anthropic", "gpt-4o") is False

    def test_validate_model_id_unknown_provider_raises(self):
        """validate_model_id raises for unknown provider."""
        with pytest.raises(ProviderNotFoundError):
            validate_model_id("unknown", "model")


class TestSearchModels:
    """Tests for search_models function."""

    def test_search_models_finds_matching(self):
        """search_models returns models matching query."""
        results = search_models("gpt-4o")
        assert len(results) > 0
        assert any("gpt-4o" in r["id"] for r in results)

    def test_search_models_with_provider_filter(self):
        """search_models respects provider filter."""
        results = search_models("claude", provider_type="anthropic")
        assert len(results) > 0
        assert all(r["lab"] == "Anthropic" for r in results)

    def test_search_models_respects_limit(self):
        """search_models respects limit parameter."""
        results = search_models("gpt", limit=3)
        assert len(results) <= 3

    def test_search_models_empty_query_returns_empty(self):
        """search_models returns empty list for empty query."""
        results = search_models("")
        assert results == []

    def test_search_models_no_matches_returns_empty(self):
        """search_models returns empty list when no matches."""
        results = search_models("zzzznonexistent12345")
        assert results == []

    def test_search_models_unknown_provider_raises(self):
        """search_models raises ProviderNotFoundError for unknown provider."""
        with pytest.raises(ProviderNotFoundError) as exc_info:
            search_models("query", provider_type="unknown-provider")
        assert "unknown-provider" in str(exc_info.value)

    def test_search_models_limit_zero_returns_empty(self):
        """search_models returns empty list when limit is 0."""
        results = search_models("gpt", limit=0)
        assert results == []

    def test_search_models_negative_limit_returns_empty(self):
        """search_models returns empty list when limit is negative."""
        results = search_models("gpt", limit=-1)
        assert results == []

    def test_search_models_across_all_providers(self):
        """search_models searches across all providers when no filter."""
        results = search_models("claude")
        # Should find Claude models from anthropic, openrouter, bedrock, vertex
        labs = {r["lab"] for r in results}
        assert "Anthropic" in labs

    def test_search_models_partial_match(self):
        """search_models finds partial matches using fuzzyfinder."""
        # 'gpt4' should match 'gpt-4o' even without exact substring
        results = search_models("gpt4")
        model_ids = [r["id"] for r in results]
        # Should find GPT-4 variants
        assert any("gpt-4" in mid for mid in model_ids)

    def test_search_models_multiple_results_ordered(self):
        """search_models returns multiple results in relevance order."""
        results = search_models("gpt", limit=10)
        # Should return multiple GPT models
        assert len(results) >= 3
        model_ids = [r["id"] for r in results]
        # All results should contain gpt
        assert all("gpt" in mid.lower() for mid in model_ids)

    def test_search_models_returns_full_model_info(self):
        """search_models returns complete ModelInfo dictionaries."""
        results = search_models("claude", limit=1)
        assert len(results) == 1
        model = results[0]
        # Verify all required fields present
        assert "id" in model
        assert "name" in model
        assert "lab" in model
        assert "context_window" in model
        assert "tags" in model
        assert isinstance(model["context_window"], int)
        assert isinstance(model["tags"], list)

    def test_search_models_filter_reduces_results(self):
        """search_models with provider filter returns subset of all results."""
        all_results = search_models("claude", limit=100)
        filtered_results = search_models("claude", provider_type="anthropic", limit=100)

        # Filtered results should be subset
        assert len(filtered_results) <= len(all_results)
        # All filtered results should be from Anthropic
        assert all(r["lab"] == "Anthropic" for r in filtered_results)
        # Filter should have reduced results (claude exists in multiple providers)
        assert len(filtered_results) < len(all_results)

    def test_search_models_whitespace_query_returns_empty(self):
        """search_models returns empty for whitespace-only query."""
        results = search_models("   ")
        assert results == []


class TestGetCatalogProviders:
    """Tests for get_catalog_providers function."""

    def test_get_catalog_providers_returns_sorted_list(self):
        """get_catalog_providers returns sorted list of providers."""
        providers = get_catalog_providers()
        assert isinstance(providers, list)
        assert providers == sorted(providers)

    def test_get_catalog_providers_includes_all(self):
        """get_catalog_providers includes all expected providers."""
        providers = get_catalog_providers()
        expected = [
            "anthropic",
            "bedrock",
            "ollama",
            "openai",
            "opencode",
            "opencode-go",
            "openrouter",
            "vertex",
            "zai",
        ]
        assert providers == expected


class TestGetModelCount:
    """Tests for get_model_count function."""

    def test_get_model_count_total(self):
        """get_model_count returns total count across all providers."""
        count = get_model_count()
        assert count > 300  # We have 378+ models from models.dev

    def test_get_model_count_by_provider(self):
        """get_model_count returns count for specific provider."""
        openai_count = get_model_count("openai")
        anthropic_count = get_model_count("anthropic")
        assert openai_count > 0
        assert anthropic_count > 0

    def test_get_model_count_unknown_provider_returns_zero(self):
        """get_model_count returns 0 for unknown provider."""
        count = get_model_count("unknown-provider")
        assert count == 0

    def test_get_model_count_ollama_is_zero(self):
        """get_model_count returns 0 for ollama (dynamic discovery)."""
        count = get_model_count("ollama")
        assert count == 0


class TestCatalogSchema:
    """Tests for catalog structure and schema validation."""

    def test_all_models_have_required_fields(self):
        """All models in catalog have required fields."""
        catalog = load_model_catalog()
        required_fields = {"id", "name", "lab", "context_window", "tags"}

        for provider, data in catalog["providers"].items():
            for model in data["models"]:
                missing = required_fields - set(model.keys())
                assert not missing, (
                    f"Model {model.get('id', 'unknown')} in {provider} missing: {missing}"
                )

    def test_all_context_windows_are_non_negative(self):
        """All context_window values are non-negative integers.

        Note: Some models (e.g., image generators) may have context_window=0.
        """
        catalog = load_model_catalog()

        for provider, data in catalog["providers"].items():
            for model in data["models"]:
                assert isinstance(model["context_window"], int)
                assert model["context_window"] >= 0, (
                    f"Invalid context_window for {model['id']}"
                )

    def test_all_tags_are_lists_of_strings(self):
        """All tags fields are lists of strings."""
        catalog = load_model_catalog()

        for provider, data in catalog["providers"].items():
            for model in data["models"]:
                assert isinstance(model["tags"], list)
                assert all(isinstance(t, str) for t in model["tags"])

    def test_model_ids_are_unique_per_provider(self):
        """Model IDs are unique within each provider."""
        catalog = load_model_catalog()

        for provider, data in catalog["providers"].items():
            ids = [m["id"] for m in data["models"]]
            assert len(ids) == len(set(ids)), f"Duplicate IDs in {provider}"
