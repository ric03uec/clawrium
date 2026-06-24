#!/usr/bin/env python3
"""Verify openclaw.json configuration against expected values.

This script is called by Ansible to verify the configuration file
was rendered correctly. It reads the actual and expected config files
and validates critical fields match.

Runs on the agent host with whatever `python3` ships there. PEP 604
union syntax (`X | Y`) became a legal *runtime* annotation in Python
3.10; on Python 3.9 (which Apple/Xcode CLI tools ship as
`/usr/bin/python3`) the same syntax raises `TypeError` when the
function definition is evaluated. `from __future__ import annotations`
defers all annotation evaluation to string form, keeping this script
compatible back to Python 3.7.
"""

from __future__ import annotations

import json
import sys


def main():
    if len(sys.argv) != 3:
        print(
            "Usage: verify_config.py <config_file> <expected_config_file>",
            file=sys.stderr,
        )
        sys.exit(1)

    config_file = sys.argv[1]
    expected_file = sys.argv[2]

    # Verify config file exists
    try:
        with open(config_file, "r") as f:
            config = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: Configuration file not found at {config_file}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError:
        print(f"ERROR: Invalid JSON in {config_file}", file=sys.stderr)
        sys.exit(1)

    # Load expected config
    try:
        with open(expected_file, "r") as f:
            expected_config = json.load(f)
    except FileNotFoundError:
        print(
            f"ERROR: Expected config file not found at {expected_file}", file=sys.stderr
        )
        sys.exit(1)
    except json.JSONDecodeError:
        print(f"ERROR: Invalid JSON in {expected_file}", file=sys.stderr)
        sys.exit(1)

    errors = []

    def _expected_model_id(expected: dict) -> str | None:
        provider = expected.get("provider", {})
        default_model = provider.get("default_model")
        if not default_model or not isinstance(default_model, str):
            return None

        provider_type = provider.get("type")
        if provider_type == "openrouter" and not default_model.startswith(
            "openrouter/"
        ):
            return f"openrouter/{default_model}"
        if provider_type == "ollama" and not default_model.startswith("ollama/"):
            return f"ollama/{default_model}"
        if provider_type == "bedrock" and not default_model.startswith("amazon-bedrock/"):
            return f"amazon-bedrock/{default_model}"
        return default_model

    # Verify model is set if provider configured
    expected_model = _expected_model_id(expected_config)
    if expected_model:
        model = config.get("agents", {}).get("defaults", {}).get("model")
        if not isinstance(model, dict):
            errors.append(
                "Model schema mismatch: expected agents.defaults.model to be an object with key 'primary'"
            )
        else:
            actual_model = model.get("primary")
            if not actual_model:
                errors.append(
                    "Model schema mismatch: missing agents.defaults.model.primary"
                )
            elif str(actual_model) != expected_model:
                errors.append(
                    f"Model mismatch: expected '{expected_model}', got '{actual_model}'"
                )

    # Verify gateway port. Use `is not None` rather than truthy: a
    # misconfigured `port: 0` (or `bind: ""`) would otherwise silently
    # skip verification and let a broken render through (S7).
    expected_port = expected_config.get("gateway", {}).get("port")
    if expected_port is not None:
        gateway_port = config.get("gateway", {}).get("port")
        if gateway_port != expected_port:
            errors.append(
                f"Gateway port mismatch: expected {expected_port}, got {gateway_port}"
            )

    # Verify gateway bind
    expected_bind = expected_config.get("gateway", {}).get("bind")
    if expected_bind is not None:
        gateway_bind = config.get("gateway", {}).get("bind")
        if gateway_bind != expected_bind:
            errors.append(
                f"Gateway bind mismatch: expected {expected_bind}, got {gateway_bind}"
            )

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)

    print("Configuration verified successfully")
    sys.exit(0)


if __name__ == "__main__":
    main()
