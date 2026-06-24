"""Tests for openclaw verify_config.py model schema checks."""

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest


def _run_verify_script(
    tmp_path: Path, config: dict, expected: dict
) -> subprocess.CompletedProcess:
    from importlib.resources import files

    template_dir = files("clawrium.platform.registry.openclaw") / "templates"
    script_path = template_dir / "verify_config.py"

    config_path = tmp_path / "openclaw.json"
    expected_path = tmp_path / "expected.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    expected_path.write_text(json.dumps(expected), encoding="utf-8")

    return subprocess.run(
        [sys.executable, str(script_path), str(config_path), str(expected_path)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_verify_config_accepts_model_primary_for_ollama(tmp_path: Path):
    config = {
        "agents": {"defaults": {"model": {"primary": "ollama/qwen3-coder:30b-128k"}}},
        "gateway": {"port": 40198, "bind": "lan"},
    }
    expected = {
        "provider": {"type": "ollama", "default_model": "qwen3-coder:30b-128k"},
        "gateway": {"port": 40198, "bind": "lan"},
    }

    result = _run_verify_script(tmp_path, config, expected)
    assert result.returncode == 0
    assert "Configuration verified successfully" in result.stdout


def test_verify_config_rejects_legacy_string_model(tmp_path: Path):
    config = {
        "agents": {"defaults": {"model": "ollama/qwen3-coder:30b-128k"}},
        "gateway": {"port": 40198, "bind": "lan"},
    }
    expected = {
        "provider": {"type": "ollama", "default_model": "qwen3-coder:30b-128k"},
        "gateway": {"port": 40198, "bind": "lan"},
    }

    result = _run_verify_script(tmp_path, config, expected)
    assert result.returncode == 1
    assert "Model schema mismatch" in result.stderr


def test_verify_config_rejects_missing_primary_key(tmp_path: Path):
    config = {
        "agents": {"defaults": {"model": {"id": "ollama/qwen3-coder:30b-128k"}}},
        "gateway": {"port": 40198, "bind": "lan"},
    }
    expected = {
        "provider": {"type": "ollama", "default_model": "qwen3-coder:30b-128k"},
        "gateway": {"port": 40198, "bind": "lan"},
    }

    result = _run_verify_script(tmp_path, config, expected)
    assert result.returncode == 1
    assert "missing agents.defaults.model.primary" in result.stderr


def test_verify_config_rejects_model_mismatch(tmp_path: Path):
    config = {
        "agents": {"defaults": {"model": {"primary": "ollama/other-model"}}},
        "gateway": {"port": 40198, "bind": "lan"},
    }
    expected = {
        "provider": {"type": "ollama", "default_model": "qwen3-coder:30b-128k"},
        "gateway": {"port": 40198, "bind": "lan"},
    }

    result = _run_verify_script(tmp_path, config, expected)
    assert result.returncode == 1
    assert "Model mismatch" in result.stderr


def test_verify_config_normalizes_openrouter_prefix(tmp_path: Path):
    config = {
        "agents": {
            "defaults": {"model": {"primary": "openrouter/anthropic/claude-sonnet-4"}}
        },
        "gateway": {"port": 40198, "bind": "lan"},
    }
    expected = {
        "provider": {
            "type": "openrouter",
            "default_model": "anthropic/claude-sonnet-4",
        },
        "gateway": {"port": 40198, "bind": "lan"},
    }

    result = _run_verify_script(tmp_path, config, expected)
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# Bedrock prefix (ATX iter-2 B1) — the prefix this branch introduced.
# Previously the script used `bedrock/`; the openclaw gateway actually
# registers its Bedrock provider as `amazon-bedrock`, so an
# `Unknown model: bedrock/<id>` was the production symptom that led to
# the bundle. These tests pin the new prefix end-to-end against the
# script — a future typo or revert would fail loudly in CI instead of
# shipping silently to a real agent. Bedrock model ids contain colons
# and dots, which makes mis-normalization especially hard to spot at
# runtime.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw_model, rendered_model",
    [
        (
            "anthropic.claude-3-7-sonnet-20250219-v1:0",
            "amazon-bedrock/anthropic.claude-3-7-sonnet-20250219-v1:0",
        ),
        ("zai.glm-5", "amazon-bedrock/zai.glm-5"),
        ("anthropic.claude-opus-4-1-v1:0", "amazon-bedrock/anthropic.claude-opus-4-1-v1:0"),
    ],
)
def test_verify_config_normalizes_bedrock_prefix(
    tmp_path: Path, raw_model: str, rendered_model: str
):
    """Operator stores a bare model id; renderer must prepend
    `amazon-bedrock/`; verify passes when actual on-host config carries
    the prefixed form."""
    config = {
        "agents": {"defaults": {"model": {"primary": rendered_model}}},
        "gateway": {"port": 40198, "bind": "lan"},
    }
    expected = {
        "provider": {"type": "bedrock", "default_model": raw_model},
        "gateway": {"port": 40198, "bind": "lan"},
    }
    result = _run_verify_script(tmp_path, config, expected)
    assert result.returncode == 0, (
        f"verify failed: stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "Configuration verified successfully" in result.stdout


def test_verify_config_bedrock_already_prefixed_not_double_prefixed(tmp_path: Path):
    """If `provider.default_model` already starts with `amazon-bedrock/`
    (operator hand-typed the prefix, or this is a re-render of an
    already-normalized value), the script must not double-prefix it to
    `amazon-bedrock/amazon-bedrock/<id>` — that's a value the gateway
    would reject at request time. The `startswith` guard inside
    `_expected_model_id` is the protection; pin its behavior here."""
    model_id = "amazon-bedrock/anthropic.claude-opus-4-1-v1:0"
    config = {
        "agents": {"defaults": {"model": {"primary": model_id}}},
        "gateway": {"port": 40198, "bind": "lan"},
    }
    expected = {
        "provider": {"type": "bedrock", "default_model": model_id},
        "gateway": {"port": 40198, "bind": "lan"},
    }
    result = _run_verify_script(tmp_path, config, expected)
    assert result.returncode == 0, (
        f"verify failed: stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "Configuration verified successfully" in result.stdout


def test_verify_config_rejects_legacy_bedrock_prefix_on_host(tmp_path: Path):
    """Negative case: if the on-host `openclaw.json` still carries the
    legacy `bedrock/<id>` form (operator hand-edited, or an old render
    was never re-synced), verify must mismatch. The fix in this branch
    deliberately does NOT auto-migrate operator data
    (CHANGELOG.md ### BREAKING), so the surfaced error is the only
    signal the operator gets that they need to update `hosts.json`."""
    config = {
        "agents": {"defaults": {"model": {"primary": "bedrock/zai.glm-5"}}},
        "gateway": {"port": 40198, "bind": "lan"},
    }
    expected = {
        "provider": {"type": "bedrock", "default_model": "zai.glm-5"},
        "gateway": {"port": 40198, "bind": "lan"},
    }
    result = _run_verify_script(tmp_path, config, expected)
    assert result.returncode == 1
    # Pin the message body — both expected and actual values must
    # surface so the operator can diff them.
    assert "Model mismatch" in result.stderr
    assert "amazon-bedrock/zai.glm-5" in result.stderr  # expected (rendered)
    assert "bedrock/zai.glm-5" in result.stderr  # actual (on host)


# ---------------------------------------------------------------------------
# Litellm prefix (issue #819) — the canonical renderer in
# `clawrium.core.render` prefixes litellm models with the *provider's
# clawctl name* (not a static type-keyed string), because each litellm
# proxy is its own custom provider in `models.providers.<name>`. The
# verify script was missing this branch, so every `clawctl agent
# configure --stage providers --provider <litellm>` failed at the
# `Verify openclaw.json configuration` task with a mismatch between the
# correctly-rendered file on disk and the raw `default_model` this
# script expected. These tests pin the new branch end-to-end against
# the script — a future regression would surface in CI.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "provider_name, raw_model, rendered_model",
    [
        # The production case: hyphenated provider name, single-segment model.
        ("clawrium-gtm-litellm", "writer", "clawrium-gtm-litellm/writer"),
        # Provider name with underscores + dots; model with a hyphen. Pins
        # that the prefix is treated as a literal string, not a regex.
        ("my_lit.proxy", "model-id", "my_lit.proxy/model-id"),
        # Multi-segment model (litellm proxies routinely fan out to
        # `<subdir>/<model>` shapes). Exercises the `startswith` guard
        # against false-positive idempotency on the wrong prefix.
        ("myproxy", "subdir/model", "myproxy/subdir/model"),
    ],
)
def test_verify_config_normalizes_litellm_prefix(
    tmp_path: Path, provider_name: str, raw_model: str, rendered_model: str
):
    config = {
        "agents": {"defaults": {"model": {"primary": rendered_model}}},
        "gateway": {"port": 40198, "bind": "lan"},
    }
    expected = {
        "provider": {
            "type": "litellm",
            "name": provider_name,
            "default_model": raw_model,
        },
        "gateway": {"port": 40198, "bind": "lan"},
    }
    result = _run_verify_script(tmp_path, config, expected)
    assert result.returncode == 0, (
        f"verify failed: stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "Configuration verified successfully" in result.stdout


def test_verify_config_litellm_already_prefixed_not_double_prefixed(tmp_path: Path):
    """If `provider.default_model` already starts with `<name>/`, do not
    double-prefix to `<name>/<name>/<model>` — that's a value the
    gateway would reject."""
    model_id = "clawrium-gtm-litellm/writer"
    config = {
        "agents": {"defaults": {"model": {"primary": model_id}}},
        "gateway": {"port": 40198, "bind": "lan"},
    }
    expected = {
        "provider": {
            "type": "litellm",
            "name": "clawrium-gtm-litellm",
            "default_model": model_id,
        },
        "gateway": {"port": 40198, "bind": "lan"},
    }
    result = _run_verify_script(tmp_path, config, expected)
    assert result.returncode == 0, (
        f"verify failed: stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "Configuration verified successfully" in result.stdout


def test_verify_config_rejects_litellm_unprefixed_on_host(tmp_path: Path):
    """Negative case: if the on-host `openclaw.json` carries the raw
    model id without the provider-name prefix, verify must mismatch."""
    config = {
        "agents": {"defaults": {"model": {"primary": "writer"}}},
        "gateway": {"port": 40198, "bind": "lan"},
    }
    expected = {
        "provider": {
            "type": "litellm",
            "name": "clawrium-gtm-litellm",
            "default_model": "writer",
        },
        "gateway": {"port": 40198, "bind": "lan"},
    }
    result = _run_verify_script(tmp_path, config, expected)
    assert result.returncode == 1
    assert "Model mismatch" in result.stderr
    assert "clawrium-gtm-litellm/writer" in result.stderr  # expected (rendered)
    # Anchor the assertion to the `got '<actual>'` half of the mismatch
    # message so a future format-string change surfaces here instead of
    # silently degrading the assertion to a one-sided check.
    assert "got 'writer'" in result.stderr


@pytest.mark.parametrize("name_value", [None, ""])
def test_verify_config_litellm_without_name_falls_through(
    tmp_path: Path, name_value
):
    """Defensive: if the provider overlay somehow lacks `name` (a bug
    upstream of this script), the litellm branch must fall through to
    the raw default_model rather than crashing or returning a malformed
    `'/<model>'`. The on-host renderer would have failed earlier, but
    this script must still produce a usable comparison.

    Parametrized over `None` (missing key) and `""` (empty string) —
    `lifecycle.py:605` uses `provider_record.get("name", "")`, so the
    empty-string branch is the realistic case if a provider was
    registered without a name."""
    config = {
        "agents": {"defaults": {"model": {"primary": "writer"}}},
        "gateway": {"port": 40198, "bind": "lan"},
    }
    provider = {"type": "litellm", "default_model": "writer"}
    if name_value is not None:
        provider["name"] = name_value
    expected = {
        "provider": provider,
        "gateway": {"port": 40198, "bind": "lan"},
    }
    result = _run_verify_script(tmp_path, config, expected)
    assert result.returncode == 0, (
        f"verify failed: stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "Configuration verified successfully" in result.stdout


# ---------------------------------------------------------------------------
# Python 3.9 compat guard — see .itx/719/01_EXECUTION.md
# ---------------------------------------------------------------------------


def test_verify_config_requires_future_annotations_import():
    """The script runs on agent hosts with whatever `python3` is on
    PATH. macOS Xcode CLI tools ship Python 3.9.6, which predates PEP
    604 union types (`X | Y`) being legal as runtime annotations. The
    `from __future__ import annotations` import in `verify_config.py`
    defers all annotation evaluation, making the file compatible with
    Python 3.7+.

    A future contributor removing that import would not fail any test
    on the developer machine (CPython 3.10+ accepts the syntax
    natively), but would crash at the first openclaw sync on macOS
    with `TypeError: unsupported operand type(s) for |: 'type' and
    'NoneType'`. This guard makes the regression a CI failure instead."""
    from importlib.resources import files

    script_path = files("clawrium.platform.registry.openclaw") / "templates" / "verify_config.py"
    source = Path(str(script_path)).read_text()
    tree = ast.parse(source)
    has_future_annotations = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "__future__"
        and any(alias.name == "annotations" for alias in node.names)
        for node in tree.body
    )
    assert has_future_annotations, (
        "verify_config.py MUST `from __future__ import annotations` for "
        "Python 3.9 compatibility on macOS hosts. See .itx/719/01_EXECUTION.md."
    )
