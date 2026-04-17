#!/usr/bin/env python3
"""Refresh model catalog from models.dev API.

This script fetches the latest model data from https://models.dev/api.json
and transforms it into Clawrium's catalog format.

Usage:
    python scripts/refresh_model_catalog.py

Output:
    Updates src/clawrium/core/providers/models.json
"""

import json
import sys
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError

MODELS_DEV_API = "https://models.dev/api.json"
OUTPUT_PATH = Path(__file__).parent.parent / "src/clawrium/core/providers/models.json"

# Map models.dev provider IDs to Clawrium provider types
PROVIDER_MAP = {
    "openai": "openai",
    "anthropic": "anthropic",
    "openrouter": "openrouter",
    "amazon-bedrock": "bedrock",
    "google-vertex": "vertex",
    "zhipuai": "zai",
}


def fetch_models_dev() -> dict:
    """Fetch the models.dev API data."""
    print(f"Fetching from {MODELS_DEV_API}...")
    try:
        req = Request(
            MODELS_DEV_API,
            headers={"User-Agent": "Clawrium/1.0 (https://github.com/ric03uec/clawrium)"}
        )
        with urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except URLError as e:
        print(f"Error fetching models.dev: {e}", file=sys.stderr)
        sys.exit(1)


def transform_model(model: dict, provider_id: str) -> dict:
    """Transform a models.dev model to Clawrium format."""
    # Build tags from model attributes
    tags = []
    if model.get("reasoning"):
        tags.append("reasoning")
    if model.get("tool_call"):
        tags.append("tool-use")
    if model.get("attachment"):
        tags.append("multimodal")
    if model.get("open_weights"):
        tags.append("open-weights")

    # Add modality-based tags
    modalities = model.get("modalities", {})
    input_mods = modalities.get("input", [])
    if "image" in input_mods:
        tags.append("vision")
    if "audio" in input_mods:
        tags.append("audio")

    # Determine lab from provider or family
    lab_map = {
        "openai": "OpenAI",
        "anthropic": "Anthropic",
        "amazon-bedrock": "AWS",
        "google-vertex": "Google",
        "zhipuai": "Zhipu AI",
    }
    lab = lab_map.get(provider_id, model.get("family", provider_id).title())

    # For openrouter, try to extract lab from model ID
    if provider_id == "openrouter":
        model_id = model.get("id", "")
        if "/" in model_id:
            lab_prefix = model_id.split("/")[0]
            lab = lab_prefix.replace("-", " ").title()

    # Get context window from limits
    limits = model.get("limit", {})
    context_window = limits.get("context", 0)

    return {
        "id": model.get("id", ""),
        "name": model.get("name", model.get("id", "")),
        "lab": lab,
        "context_window": context_window,
        "tags": tags if tags else ["general"],
    }


def transform_catalog(data: dict) -> dict:
    """Transform models.dev data to Clawrium catalog format."""
    catalog = {
        "version": "1.0.0",
        "source": "https://models.dev",
        "providers": {},
    }

    for source_id, target_id in PROVIDER_MAP.items():
        if source_id not in data:
            print(f"Warning: Provider '{source_id}' not found in models.dev")
            continue

        provider_data = data[source_id]
        models = provider_data.get("models", {})

        transformed_models = []
        for model_id, model in models.items():
            transformed = transform_model(model, source_id)
            if transformed["id"]:  # Only include models with valid IDs
                transformed_models.append(transformed)

        # Sort by name for consistency
        transformed_models.sort(key=lambda m: m["name"])

        catalog["providers"][target_id] = {"models": transformed_models}
        print(f"  {target_id}: {len(transformed_models)} models")

    # Add empty ollama entry (dynamic discovery)
    catalog["providers"]["ollama"] = {"models": []}
    print("  ollama: 0 models (dynamic discovery)")

    return catalog


def main():
    """Main entry point."""
    print("Refreshing model catalog from models.dev\n")

    # Fetch source data
    data = fetch_models_dev()
    print(f"Fetched {len(data)} providers\n")

    # Transform to our format
    print("Transforming models:")
    catalog = transform_catalog(data)

    # Calculate totals
    total_models = sum(
        len(p["models"]) for p in catalog["providers"].values()
    )
    print(f"\nTotal: {total_models} models across {len(catalog['providers'])} providers")

    # Write output
    print(f"\nWriting to {OUTPUT_PATH}...")
    with open(OUTPUT_PATH, "w") as f:
        json.dump(catalog, f, indent=2)
    print("Done!")


if __name__ == "__main__":
    main()
