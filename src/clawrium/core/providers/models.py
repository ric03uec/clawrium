"""Model catalog operations for Clawrium.

Provides functions for loading, searching, and validating model IDs
from the JSON model catalog.
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import TypedDict

from fuzzyfinder import fuzzyfinder


class ModelInfo(TypedDict):
    """Model metadata structure."""

    id: str
    name: str
    lab: str
    context_window: int
    tags: list[str]


class ProviderModels(TypedDict):
    """Provider models structure."""

    models: list[ModelInfo]


class ModelCatalog(TypedDict):
    """Root catalog structure."""

    version: str
    providers: dict[str, ProviderModels]


CATALOG_FILE = Path(__file__).parent / "models.json"


class ModelNotFoundError(Exception):
    """Raised when a model ID is not found in the catalog."""

    pass


class ProviderNotFoundError(Exception):
    """Raised when a provider is not found in the catalog."""

    pass


class CatalogLoadError(Exception):
    """Raised when the model catalog cannot be loaded."""

    pass


@lru_cache(maxsize=1)
def load_model_catalog() -> ModelCatalog:
    """Load the model catalog from models.json.

    The catalog is bundled with the package and contains metadata for all
    supported provider models. It is cached after the first load.

    Returns:
        ModelCatalog dictionary with version and providers.

    Raises:
        CatalogLoadError: If models.json cannot be loaded (missing or malformed).
    """
    try:
        with open(CATALOG_FILE) as f:
            return json.load(f)
    except FileNotFoundError:
        raise CatalogLoadError(
            f"Model catalog not found at {CATALOG_FILE}. The package may be corrupted."
        )
    except json.JSONDecodeError as e:
        raise CatalogLoadError(
            f"Model catalog is malformed: {e}. The package may be corrupted."
        )


def get_models_for_provider(provider_type: str) -> list[ModelInfo]:
    """Get all models for a specific provider type.

    Args:
        provider_type: Provider type (e.g., 'openai', 'anthropic').

    Returns:
        List of ModelInfo dictionaries for the provider.

    Raises:
        ProviderNotFoundError: If provider_type is not in the catalog.
    """
    catalog = load_model_catalog()
    if provider_type not in catalog["providers"]:
        valid_providers = ", ".join(sorted(catalog["providers"].keys()))
        raise ProviderNotFoundError(
            f"Provider '{provider_type}' not found. Valid providers: {valid_providers}"
        )
    return catalog["providers"][provider_type]["models"]


def get_model_ids_for_provider(provider_type: str) -> list[str]:
    """Get just the model IDs for a provider (for backward compatibility).

    Args:
        provider_type: Provider type (e.g., 'openai', 'anthropic').

    Returns:
        List of model ID strings.

    Raises:
        ProviderNotFoundError: If provider_type is not in the catalog.
    """
    models = get_models_for_provider(provider_type)
    return [m["id"] for m in models]


def validate_model_id(provider_type: str, model_id: str) -> bool:
    """Check if a model ID is valid for a provider.

    Args:
        provider_type: Provider type (e.g., 'openai', 'anthropic').
        model_id: Model ID to validate.

    Returns:
        True if the model ID exists for the provider.

    Raises:
        ProviderNotFoundError: If provider_type is not in the catalog.
    """
    model_ids = get_model_ids_for_provider(provider_type)
    return model_id in model_ids


def search_models(
    query: str, provider_type: str | None = None, limit: int = 10
) -> list[ModelInfo]:
    """Fuzzy search for models across providers.

    Args:
        query: Search query string. Empty string returns no results.
        provider_type: Optional provider to limit search to.
        limit: Maximum number of results to return (must be positive).

    Returns:
        List of matching ModelInfo dictionaries, sorted by relevance.

    Raises:
        ProviderNotFoundError: If provider_type is specified but not in catalog.
    """
    if not query or limit <= 0:
        return []

    catalog = load_model_catalog()

    # Collect all models (or just from specified provider)
    all_models: list[ModelInfo] = []
    if provider_type:
        if provider_type not in catalog["providers"]:
            valid_providers = ", ".join(sorted(catalog["providers"].keys()))
            raise ProviderNotFoundError(
                f"Provider '{provider_type}' not found. Valid providers: {valid_providers}"
            )
        all_models = catalog["providers"][provider_type]["models"]
    else:
        for provider_data in catalog["providers"].values():
            all_models.extend(provider_data["models"])

    if not all_models:
        return []

    # Create lookup by ID for result mapping
    model_by_id = {m["id"]: m for m in all_models}

    # Fuzzy search on model IDs
    matching_ids = list(fuzzyfinder(query, model_by_id.keys()))

    # Return full model info for matches
    return [model_by_id[mid] for mid in matching_ids[:limit]]


def get_catalog_providers() -> list[str]:
    """Get list of all provider types in the catalog.

    Returns:
        Sorted list of provider type strings.
    """
    catalog = load_model_catalog()
    return sorted(catalog["providers"].keys())


def get_model_count(provider_type: str | None = None) -> int:
    """Get total model count, optionally filtered by provider.

    Args:
        provider_type: Optional provider to count models for.

    Returns:
        Number of models.
    """
    catalog = load_model_catalog()
    if provider_type:
        if provider_type not in catalog["providers"]:
            return 0
        return len(catalog["providers"][provider_type]["models"])
    return sum(len(p["models"]) for p in catalog["providers"].values())
