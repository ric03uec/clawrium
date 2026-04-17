#!/usr/bin/env python3
"""Generate provider documentation from models.json catalog.

This script reads the model catalog and generates markdown tables
grouped by lab for each provider's documentation.

Usage:
    python scripts/generate_provider_docs.py

Output:
    Updates provider docs in /docs/ and /website/docs/ directories
    by replacing content between MODEL-TABLE markers.
"""

import json
import re
import sys
from pathlib import Path

MODELS_JSON = Path(__file__).parent.parent / "src/clawrium/core/providers/models.json"
DOCS_PROVIDERS = Path(__file__).parent.parent / "docs/agent-support/providers"
WEBSITE_PROVIDERS = Path(__file__).parent.parent / "website/docs/agent-support/providers"

START_MARKER = "<!-- MODEL-TABLE:START -->"
END_MARKER = "<!-- MODEL-TABLE:END -->"


def load_catalog() -> dict:
    """Load the models.json catalog."""
    if not MODELS_JSON.exists():
        print(f"Error: {MODELS_JSON} not found", file=sys.stderr)
        sys.exit(1)

    with open(MODELS_JSON) as f:
        return json.load(f)


def format_context_window(context: int) -> str:
    """Format context window for display.

    Matches the formatting in src/clawrium/cli/provider.py
    """
    if context >= 1_000_000:
        return f"{context // 1_000_000}M"
    elif context >= 1000:
        return f"{context // 1000}K"
    elif context > 0:
        return str(context)
    return "-"


def generate_model_table(models: list, provider_id: str) -> str:
    """Generate markdown table for models, grouped by lab."""
    if not models:
        if provider_id == "ollama":
            return "*Ollama models are discovered dynamically from local installation.*\n"
        return "*No models available.*\n"

    # Group models by lab
    labs: dict[str, list] = {}
    for model in models:
        lab = model.get("lab", "Other")
        if lab not in labs:
            labs[lab] = []
        labs[lab].append(model)

    # Sort labs alphabetically, but put the "primary" lab first if it matches provider
    primary_labs = {
        "openai": "OpenAI",
        "anthropic": "Anthropic",
        "vertex": "Google",
        "bedrock": "AWS",
        "zai": "Zhipu AI",
    }
    primary = primary_labs.get(provider_id)

    sorted_labs = sorted(labs.keys())
    if primary and primary in sorted_labs:
        sorted_labs.remove(primary)
        sorted_labs.insert(0, primary)

    lines = []
    single_lab = len(labs) == 1

    for lab in sorted_labs:
        lab_models = sorted(labs[lab], key=lambda m: m.get("name", ""))

        # Only add lab header if multiple labs
        if not single_lab:
            lines.append(f"### {lab}\n")

        lines.append("| Model ID | Name | Context |")
        lines.append("|----------|------|---------|")

        for model in lab_models:
            model_id = model.get("id", "")
            name = model.get("name", model_id)
            context = format_context_window(model.get("context_window", 0))
            lines.append(f"| `{model_id}` | {name} | {context} |")

        lines.append("")

    return "\n".join(lines)


def update_doc_file(doc_path: Path, table_content: str) -> bool:
    """Update a documentation file with generated table content.

    Returns True if file was updated, False if markers not found.
    """
    if not doc_path.exists():
        return False

    content = doc_path.read_text()

    # Check for markers
    if START_MARKER not in content or END_MARKER not in content:
        return False

    # Replace content between markers
    pattern = re.compile(
        rf"{re.escape(START_MARKER)}.*?{re.escape(END_MARKER)}",
        re.DOTALL
    )
    replacement = f"{START_MARKER}\n{table_content}{END_MARKER}"
    new_content = pattern.sub(replacement, content)

    doc_path.write_text(new_content)
    return True


def process_provider(provider_id: str, models: list, docs_dir: Path, dry_run: bool = False) -> tuple[bool, str]:
    """Process a single provider's documentation.

    Returns (success, message) tuple.
    """
    doc_file = docs_dir / f"{provider_id}.md"
    if provider_id == "bedrock":
        doc_file = docs_dir / "bedrock.md"

    if not doc_file.exists():
        return False, f"Doc file not found: {doc_file}"

    table_content = generate_model_table(models, provider_id)

    if dry_run:
        return True, f"Would update {doc_file}"

    if update_doc_file(doc_file, table_content):
        return True, f"Updated {doc_file}"
    else:
        return False, f"No markers found in {doc_file}"


def main():
    """Main entry point."""
    print("Generating provider documentation from models.json\n")

    # Load catalog
    catalog = load_catalog()
    providers = catalog.get("providers", {})

    print(f"Found {len(providers)} providers in catalog\n")

    # Process each directory
    for docs_dir in [DOCS_PROVIDERS, WEBSITE_PROVIDERS]:
        if not docs_dir.exists():
            print(f"Warning: {docs_dir} not found, skipping")
            continue

        print(f"Processing {docs_dir}:")

        for provider_id, provider_data in providers.items():
            models = provider_data.get("models", [])
            success, message = process_provider(provider_id, models, docs_dir)

            status = "[OK]" if success else "[SKIP]"
            print(f"  {status} {provider_id}: {message}")

        print()

    print("Done!")


if __name__ == "__main__":
    main()
