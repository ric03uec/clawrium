"""Tests for openclaw verify_config.py model schema checks."""

import json
import subprocess
import sys
from pathlib import Path


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
