"""Tests for `clawctl provider registry` CRUD verbs.

The fleet_dir fixture isolates `XDG_CONFIG_HOME` so providers.json,
secrets.json, and hosts.json live inside a tmp directory.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from typer.testing import CliRunner

from clawrium.cli import app
from clawrium.core.providers.storage import get_provider
from clawrium.core.render import build_render_inputs, render_hermes, render_openclaw

runner = CliRunner()


def _mock_litellm_probe():
    """Patch `fetch_litellm_models` so create/edit don't hit the network.

    Returns a `with`-context patch. The mock returns a single fake model
    id so the `available_models` field gets populated like a real probe.
    """
    return patch(
        "clawrium.cli.clawctl.provider.fetch_litellm_models",
        return_value=["writer"],
    )


def test_create_anthropic_with_api_key(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(
        app,
        [
            "provider",
            "registry",
            "create",
            "my-anthropic",
            "--type",
            "anthropic",
            "--model",
            "claude-opus-4-20250514",
            "--api-key",
            "sk-test-abc",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "provider/my-anthropic" in result.output
    assert "created" in result.output


def test_create_requires_api_key_on_non_tty(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(
        app,
        ["provider", "registry", "create", "p", "--type", "anthropic"],
    )
    assert result.exit_code != 0
    assert "missing required flag --api-key" in result.output


def test_create_api_key_stdin_reads_value(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(
        app,
        [
            "provider",
            "registry",
            "create",
            "stdin-anthropic",
            "--type",
            "anthropic",
            "--api-key-stdin",
        ],
        input="sk-piped-key\n",
    )
    assert result.exit_code == 0, result.output


def test_create_duplicate_fails(fleet_dir, stdin_not_tty) -> None:
    runner.invoke(
        app,
        [
            "provider",
            "registry",
            "create",
            "dup",
            "--type",
            "anthropic",
            "--api-key",
            "sk-x",
        ],
    )
    result = runner.invoke(
        app,
        [
            "provider",
            "registry",
            "create",
            "dup",
            "--type",
            "anthropic",
            "--api-key",
            "sk-x",
        ],
    )
    assert result.exit_code != 0
    assert "already exists" in result.output


def test_create_bedrock_with_aws_triplet(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(
        app,
        [
            "provider",
            "registry",
            "create",
            "my-bedrock",
            "--type",
            "bedrock",
            "--access-key",
            "AKIA",
            "--secret-key",
            "secret",
            "--region",
            "us-west-2",
        ],
    )
    assert result.exit_code == 0, result.output


def test_create_bedrock_missing_access_key_fails(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(
        app,
        [
            "provider",
            "registry",
            "create",
            "no-creds",
            "--type",
            "bedrock",
            "--secret-key",
            "secret",
        ],
    )
    assert result.exit_code != 0
    assert "missing required flag --access-key" in result.output


def test_get_lists_providers(fleet_dir, stdin_not_tty) -> None:
    runner.invoke(
        app,
        [
            "provider",
            "registry",
            "create",
            "p1",
            "--type",
            "anthropic",
            "--api-key",
            "k",
        ],
    )
    result = runner.invoke(app, ["provider", "registry", "get"])
    assert result.exit_code == 0, result.output
    assert "p1" in result.output
    assert "anthropic" in result.output


def test_get_json_emits_array(fleet_dir, stdin_not_tty) -> None:
    runner.invoke(
        app,
        [
            "provider",
            "registry",
            "create",
            "jp",
            "--type",
            "anthropic",
            "--api-key",
            "k",
        ],
    )
    result = runner.invoke(app, ["provider", "registry", "get", "-o", "json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, list)
    assert any(p["name"] == "jp" for p in data)


def test_get_name_format(fleet_dir, stdin_not_tty) -> None:
    runner.invoke(
        app,
        [
            "provider",
            "registry",
            "create",
            "n1",
            "--type",
            "anthropic",
            "--api-key",
            "k",
        ],
    )
    result = runner.invoke(app, ["provider", "registry", "get", "-o", "name"])
    assert result.exit_code == 0
    assert "provider/n1" in result.output


def test_get_types_lists_catalog(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(app, ["provider", "registry", "get", "--types"])
    assert result.exit_code == 0
    # PROVIDER_MODELS has at least anthropic + openai + ollama
    assert "anthropic" in result.output
    assert "ollama" in result.output


def test_describe_unknown_fails(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(app, ["provider", "registry", "describe", "missing"])
    assert result.exit_code != 0
    assert "not found" in result.output


def test_describe_known(fleet_dir, stdin_not_tty) -> None:
    runner.invoke(
        app,
        [
            "provider",
            "registry",
            "create",
            "d1",
            "--type",
            "anthropic",
            "--api-key",
            "k",
        ],
    )
    result = runner.invoke(app, ["provider", "registry", "describe", "d1"])
    assert result.exit_code == 0
    assert "Name:" in result.output
    assert "d1" in result.output
    assert "anthropic" in result.output


def test_edit_model(fleet_dir, stdin_not_tty) -> None:
    runner.invoke(
        app,
        [
            "provider",
            "registry",
            "create",
            "e1",
            "--type",
            "anthropic",
            "--model",
            "old-model",
            "--api-key",
            "k",
        ],
    )
    result = runner.invoke(
        app,
        ["provider", "registry", "edit", "e1", "--model", "new-model"],
    )
    assert result.exit_code == 0, result.output
    desc = runner.invoke(app, ["provider", "registry", "describe", "e1", "-o", "json"])
    data = json.loads(desc.output)
    assert data[0]["model"] == "new-model"


def test_edit_no_args_fails(fleet_dir, stdin_not_tty) -> None:
    runner.invoke(
        app,
        [
            "provider",
            "registry",
            "create",
            "e2",
            "--type",
            "anthropic",
            "--api-key",
            "k",
        ],
    )
    result = runner.invoke(app, ["provider", "registry", "edit", "e2"])
    assert result.exit_code != 0


def test_delete_requires_yes_on_non_tty(fleet_dir, stdin_not_tty) -> None:
    runner.invoke(
        app,
        [
            "provider",
            "registry",
            "create",
            "dx",
            "--type",
            "anthropic",
            "--api-key",
            "k",
        ],
    )
    result = runner.invoke(app, ["provider", "registry", "delete", "dx"])
    assert result.exit_code != 0
    assert "--yes" in result.output


def test_delete_with_yes_removes_record(fleet_dir, stdin_not_tty) -> None:
    runner.invoke(
        app,
        [
            "provider",
            "registry",
            "create",
            "dy",
            "--type",
            "anthropic",
            "--api-key",
            "k",
        ],
    )
    result = runner.invoke(app, ["provider", "registry", "delete", "dy", "--yes"])
    assert result.exit_code == 0
    # Now describing returns not-found.
    desc = runner.invoke(app, ["provider", "registry", "describe", "dy"])
    assert desc.exit_code != 0


def test_create_opencode_persists_default_endpoint(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(
        app,
        [
            "provider",
            "registry",
            "create",
            "my-opencode",
            "--type",
            "opencode",
            "--model",
            "kimi-k2.5",
            "--api-key",
            "sk-test",
        ],
    )
    assert result.exit_code == 0, result.output
    providers = json.loads((fleet_dir / "providers.json").read_text())
    record = next(p for p in providers if p["name"] == "my-opencode")
    assert record["endpoint"] == "https://opencode.ai/zen/v1"


def test_create_opencode_go_persists_default_endpoint(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(
        app,
        [
            "provider",
            "registry",
            "create",
            "my-opencode-go",
            "--type",
            "opencode-go",
            "--model",
            "deepseek-v4-flash",
            "--api-key",
            "sk-test",
        ],
    )
    assert result.exit_code == 0, result.output
    providers = json.loads((fleet_dir / "providers.json").read_text())
    record = next(p for p in providers if p["name"] == "my-opencode-go")
    assert record["endpoint"] == "https://opencode.ai/zen/go/v1"


def test_create_opencode_end_to_end_renders_hermes(hermes_fleet_dir, stdin_not_tty) -> None:
    """W3: default endpoint persisted at create time flows through build_render_inputs + render_hermes."""
    runner.invoke(
        app,
        [
            "provider",
            "registry",
            "create",
            "ocg",
            "--type",
            "opencode-go",
            "--model",
            "deepseek-v4-flash",
            "--api-key",
            "sk-test",
        ],
    )
    runner.invoke(
        app,
        [
            "agent",
            "provider",
            "attach",
            "ocg",
            "--agent",
            "sage-hermes",
            "--role",
            "primary",
        ],
    )
    inputs = build_render_inputs("sage-hermes")
    out = render_hermes(inputs)
    yaml = out.files[".hermes/config.yaml"]
    assert 'provider: "custom"' in yaml
    assert "https://opencode.ai/zen/go/v1" in yaml
    assert "deepseek-v4-flash" in yaml


def test_create_opencode_end_to_end_renders_openclaw(fleet_dir, stdin_not_tty) -> None:
    """W4: OPENAI_BASE_URL is rendered when an opencode provider is attached to openclaw."""
    runner.invoke(
        app,
        [
            "provider",
            "registry",
            "create",
            "ocg",
            "--type",
            "opencode-go",
            "--model",
            "deepseek-v4-flash",
            "--api-key",
            "sk-test",
        ],
    )
    runner.invoke(
        app,
        [
            "agent",
            "provider",
            "attach",
            "ocg",
            "--agent",
            "wise-hypatia",
        ],
    )
    inputs = build_render_inputs("wise-hypatia")
    out = render_openclaw(inputs)
    env = out.files[".openclaw/env"]
    assert "OPENCODE_API_KEY='sk-test'" in env
    assert "OPENAI_BASE_URL='https://opencode.ai/zen/go/v1'" in env
    assert "OPENCLAW_DEFAULT_MODEL='deepseek-v4-flash'" in env


# ---------------------------------------------------------------------------
# #831: `--context-window` CLI flag (litellm only)
#
# Pins the operator-supplied context_length used by render_hermes /
# render_openclaw. The flag is litellm-only — non-litellm types are
# rejected upfront so the operator doesn't silently set an unused value.
# ---------------------------------------------------------------------------


def test_create_litellm_with_context_window_persists_field(
    fleet_dir, stdin_not_tty
) -> None:
    """`provider registry create --type litellm --context-window 131072` writes the field."""
    with _mock_litellm_probe():
        result = runner.invoke(
            app,
            [
                "provider",
                "registry",
                "create",
                "clawrium-gtm-litellm",
                "--type",
                "litellm",
                "--litellm-url",
                "http://192.168.1.17:4000",
                "--model",
                "writer",
                "--api-key",
                "sk-master-1",
                "--context-window",
                "131072",
            ],
        )
    assert result.exit_code == 0, result.output
    record = get_provider("clawrium-gtm-litellm")
    assert record is not None
    assert record.get("context_window") == 131072


def test_create_litellm_without_context_window_omits_field(
    fleet_dir, stdin_not_tty
) -> None:
    """Default (no flag) does not set `context_window` on the record at all."""
    with _mock_litellm_probe():
        result = runner.invoke(
            app,
            [
                "provider",
                "registry",
                "create",
                "lt-no-ctx",
                "--type",
                "litellm",
                "--litellm-url",
                "http://10.0.0.5:4000",
                "--model",
                "writer",
                "--api-key",
                "sk-master-2",
            ],
        )
    assert result.exit_code == 0, result.output
    record = get_provider("lt-no-ctx")
    assert record is not None
    # The key is omitted entirely (renderer falls through to default).
    assert "context_window" not in record


def test_create_context_window_rejected_for_non_litellm(
    fleet_dir, stdin_not_tty
) -> None:
    """`--context-window` on a non-litellm `--type` exits non-zero."""
    result = runner.invoke(
        app,
        [
            "provider",
            "registry",
            "create",
            "anth",
            "--type",
            "anthropic",
            "--api-key",
            "sk-x",
            "--context-window",
            "200000",
        ],
    )
    assert result.exit_code != 0
    assert "--context-window only valid for litellm" in result.output


def test_create_context_window_rejects_non_positive(
    fleet_dir, stdin_not_tty
) -> None:
    """`--context-window 0` or negative exits non-zero."""
    result = runner.invoke(
        app,
        [
            "provider",
            "registry",
            "create",
            "lt-bad",
            "--type",
            "litellm",
            "--litellm-url",
            "http://10.0.0.5:4000",
            "--model",
            "writer",
            "--api-key",
            "sk-x",
            "--context-window",
            "0",
        ],
    )
    assert result.exit_code != 0
    assert "--context-window must be a positive integer" in result.output


def test_edit_litellm_adds_context_window(fleet_dir, stdin_not_tty) -> None:
    """`edit --context-window N` on an existing litellm record persists the value."""
    with _mock_litellm_probe():
        runner.invoke(
            app,
            [
                "provider",
                "registry",
                "create",
                "lt-edit",
                "--type",
                "litellm",
                "--litellm-url",
                "http://10.0.0.5:4000",
                "--model",
                "writer",
                "--api-key",
                "sk-y",
            ],
        )
    # Sanity: field absent before edit.
    assert "context_window" not in (get_provider("lt-edit") or {})

    result = runner.invoke(
        app,
        [
            "provider",
            "registry",
            "edit",
            "lt-edit",
            "--context-window",
            "131072",
        ],
    )
    assert result.exit_code == 0, result.output
    assert get_provider("lt-edit").get("context_window") == 131072


def test_edit_context_window_rejected_for_non_litellm(
    fleet_dir, stdin_not_tty
) -> None:
    """`edit --context-window` on a non-litellm provider exits non-zero."""
    runner.invoke(
        app,
        [
            "provider",
            "registry",
            "create",
            "edit-anth",
            "--type",
            "anthropic",
            "--api-key",
            "k",
        ],
    )
    result = runner.invoke(
        app,
        [
            "provider",
            "registry",
            "edit",
            "edit-anth",
            "--context-window",
            "131072",
        ],
    )
    assert result.exit_code != 0
    assert "--context-window only valid for litellm" in result.output
