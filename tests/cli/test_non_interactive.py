"""Non-interactive contract sweep across bundles 2/3/4.

Every command added by the kubectl-style CLI rewrite (#435) MUST
run to completion when stdin is closed and a complete flag set is
supplied. This test exercises one representative invocation per
command (the verb most likely to demand interactive input) and
asserts exit-code 0.

It is the codified version of plan §7's hard rule:

> If all mandatory flags are supplied, the command MUST run to
> completion with no stdin reads.
"""

from __future__ import annotations

from typer.testing import CliRunner

from clawrium.cli import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers — every test creates its dependencies inside the same isolated
# `fleet_dir`; XDG_CONFIG_HOME is overridden via the conftest fixture.
# ---------------------------------------------------------------------------


def _create_provider(name: str = "p1") -> None:
    result = runner.invoke(
        app,
        [
            "provider",
            "registry",
            "create",
            name,
            "--type",
            "anthropic",
            "--api-key",
            "k",
        ],
    )
    assert result.exit_code == 0, result.output


def _create_channel(name: str = "c1", channel_type: str = "discord") -> None:
    result = runner.invoke(
        app,
        [
            "channel",
            "registry",
            "create",
            name,
            "--type",
            channel_type,
            "--token",
            "t",
        ],
    )
    assert result.exit_code == 0, result.output


def _create_integration(name: str = "i1") -> None:
    result = runner.invoke(
        app,
        [
            "integration",
            "registry",
            "create",
            name,
            "--type",
            "github",
            "--credential",
            "GITHUB_TOKEN=t",
        ],
    )
    assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# Bundle 2 — service / meta
# ---------------------------------------------------------------------------


def test_service_init_noninteractive(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(app, ["service", "init"])
    assert result.exit_code == 0, result.output


def test_service_start_placeholder(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(app, ["service", "start"])
    assert result.exit_code == 0
    assert "Not implemented" in result.output


def test_version_command(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0


def test_completion_bash(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(app, ["completion", "bash"])
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Bundle 3 — host + agent Pattern B
# ---------------------------------------------------------------------------


def test_host_get_noninteractive(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(app, ["host", "get"])
    assert result.exit_code == 0


def test_host_describe_noninteractive(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(app, ["host", "describe", "wolf-i"])
    assert result.exit_code == 0


def test_host_label_noninteractive(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(app, ["host", "label", "wolf-i", "stage=qa"])
    assert result.exit_code == 0


def test_agent_get_noninteractive(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(app, ["agent", "get"])
    assert result.exit_code == 0


def test_agent_describe_noninteractive(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(app, ["agent", "describe", "wise-hypatia"])
    assert result.exit_code == 0


def test_agent_registry_get_noninteractive(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(app, ["agent", "registry", "get"])
    assert result.exit_code == 0


def test_host_registry_get_noninteractive(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(app, ["host", "registry", "get"])
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Bundle 4 — Pattern A registries
# ---------------------------------------------------------------------------


def test_provider_registry_create_noninteractive(fleet_dir, stdin_not_tty) -> None:
    _create_provider("piA")


def test_provider_registry_get_noninteractive(fleet_dir, stdin_not_tty) -> None:
    _create_provider("piG")
    result = runner.invoke(app, ["provider", "registry", "get"])
    assert result.exit_code == 0


def test_provider_registry_describe_noninteractive(fleet_dir, stdin_not_tty) -> None:
    _create_provider("piD")
    result = runner.invoke(app, ["provider", "registry", "describe", "piD"])
    assert result.exit_code == 0


def test_provider_registry_edit_noninteractive(fleet_dir, stdin_not_tty) -> None:
    _create_provider("piE")
    result = runner.invoke(
        app, ["provider", "registry", "edit", "piE", "--model", "newer"]
    )
    assert result.exit_code == 0


def test_provider_registry_delete_noninteractive(fleet_dir, stdin_not_tty) -> None:
    _create_provider("piX")
    result = runner.invoke(app, ["provider", "registry", "delete", "piX", "--yes"])
    assert result.exit_code == 0


def test_channel_registry_create_noninteractive(fleet_dir, stdin_not_tty) -> None:
    _create_channel("chA")


def test_channel_registry_get_noninteractive(fleet_dir, stdin_not_tty) -> None:
    _create_channel("chG")
    result = runner.invoke(app, ["channel", "registry", "get"])
    assert result.exit_code == 0


def test_channel_registry_describe_noninteractive(fleet_dir, stdin_not_tty) -> None:
    _create_channel("chD")
    result = runner.invoke(app, ["channel", "registry", "describe", "chD"])
    assert result.exit_code == 0


def test_channel_registry_edit_noninteractive(fleet_dir, stdin_not_tty) -> None:
    _create_channel("chE", channel_type="slack")
    result = runner.invoke(
        app,
        [
            "channel",
            "registry",
            "edit",
            "chE",
            "--stream-mode",
            "append",
        ],
    )
    assert result.exit_code == 0


def test_channel_registry_delete_noninteractive(fleet_dir, stdin_not_tty) -> None:
    _create_channel("chX")
    result = runner.invoke(app, ["channel", "registry", "delete", "chX", "--yes"])
    assert result.exit_code == 0


def test_integration_registry_create_noninteractive(fleet_dir, stdin_not_tty) -> None:
    _create_integration("iA")


def test_integration_registry_get_noninteractive(fleet_dir, stdin_not_tty) -> None:
    _create_integration("iG")
    result = runner.invoke(app, ["integration", "registry", "get"])
    assert result.exit_code == 0


def test_integration_registry_edit_noninteractive(fleet_dir, stdin_not_tty) -> None:
    _create_integration("iE")
    result = runner.invoke(
        app,
        [
            "integration",
            "registry",
            "edit",
            "iE",
            "--credential",
            "GITHUB_TOKEN=rotated",
        ],
    )
    assert result.exit_code == 0


def test_skill_registry_get_noninteractive(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(app, ["skill", "registry", "get"])
    assert result.exit_code == 0


def test_mcp_registry_get_noninteractive(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(app, ["mcp", "registry", "get"])
    assert result.exit_code == 0
    assert "Not implemented" in result.output


# ---------------------------------------------------------------------------
# Bundle 4 — per-agent attachments
# ---------------------------------------------------------------------------


def test_agent_provider_attach_get_noninteractive(fleet_dir, stdin_not_tty) -> None:
    _create_provider("aap")
    result = runner.invoke(
        app, ["agent", "provider", "attach", "aap", "--agent", "wise-hypatia"]
    )
    assert result.exit_code == 0
    listed = runner.invoke(app, ["agent", "provider", "get", "--agent", "wise-hypatia"])
    assert listed.exit_code == 0


def test_agent_channel_attach_get_noninteractive(fleet_dir, stdin_not_tty) -> None:
    _create_channel("aac")
    result = runner.invoke(
        app, ["agent", "channel", "attach", "aac", "--agent", "wise-hypatia"]
    )
    assert result.exit_code == 0
    listed = runner.invoke(app, ["agent", "channel", "get", "--agent", "wise-hypatia"])
    assert listed.exit_code == 0


def test_agent_integration_attach_get_noninteractive(fleet_dir, stdin_not_tty) -> None:
    _create_integration("aai")
    result = runner.invoke(
        app, ["agent", "integration", "attach", "aai", "--agent", "wise-hypatia"]
    )
    assert result.exit_code == 0
    listed = runner.invoke(
        app, ["agent", "integration", "get", "--agent", "wise-hypatia"]
    )
    assert listed.exit_code == 0


def test_agent_secret_create_get_noninteractive(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(
        app,
        [
            "agent",
            "secret",
            "create",
            "FOO",
            "--agent",
            "wise-hypatia",
            "--value",
            "bar",
        ],
    )
    assert result.exit_code == 0
    listed = runner.invoke(app, ["agent", "secret", "get", "--agent", "wise-hypatia"])
    assert listed.exit_code == 0


# ---------------------------------------------------------------------------
# Bundle 4 — detach verbs and remaining sub-resource paths (ATX iter-2 W1)
# ---------------------------------------------------------------------------


def test_agent_provider_detach_noninteractive(fleet_dir, stdin_not_tty) -> None:
    _create_provider("dp")
    runner.invoke(
        app, ["agent", "provider", "attach", "dp", "--agent", "wise-hypatia"]
    )
    result = runner.invoke(
        app, ["agent", "provider", "detach", "dp", "--agent", "wise-hypatia"]
    )
    assert result.exit_code == 0


def test_agent_channel_detach_noninteractive(fleet_dir, stdin_not_tty) -> None:
    _create_channel("dc")
    runner.invoke(
        app, ["agent", "channel", "attach", "dc", "--agent", "wise-hypatia"]
    )
    result = runner.invoke(
        app, ["agent", "channel", "detach", "dc", "--agent", "wise-hypatia"]
    )
    assert result.exit_code == 0


def test_agent_integration_detach_noninteractive(fleet_dir, stdin_not_tty) -> None:
    _create_integration("di")
    runner.invoke(
        app, ["agent", "integration", "attach", "di", "--agent", "wise-hypatia"]
    )
    result = runner.invoke(
        app, ["agent", "integration", "detach", "di", "--agent", "wise-hypatia"]
    )
    assert result.exit_code == 0


def test_agent_secret_describe_delete_import_noninteractive(
    fleet_dir, stdin_not_tty, tmp_path
) -> None:
    # describe
    runner.invoke(
        app,
        [
            "agent",
            "secret",
            "create",
            "FOO",
            "--agent",
            "wise-hypatia",
            "--value",
            "v",
        ],
    )
    r = runner.invoke(
        app, ["agent", "secret", "describe", "FOO", "--agent", "wise-hypatia"]
    )
    assert r.exit_code == 0
    # delete with --yes
    r = runner.invoke(
        app,
        [
            "agent",
            "secret",
            "delete",
            "FOO",
            "--agent",
            "wise-hypatia",
            "--yes",
        ],
    )
    assert r.exit_code == 0
    # import from --from-file
    env = tmp_path / ".env"
    env.write_text("A=1\nB=2\n")
    r = runner.invoke(
        app,
        [
            "agent",
            "secret",
            "import",
            "--agent",
            "wise-hypatia",
            "--from-file",
            str(env),
        ],
    )
    assert r.exit_code == 0


def test_provider_registry_refresh_requires_ollama_type(
    fleet_dir, stdin_not_tty
) -> None:
    """`refresh` on a non-ollama provider exits non-zero with a clear error,
    which still honors the non-interactive contract (no prompts)."""
    _create_provider("rfp")
    result = runner.invoke(app, ["provider", "registry", "refresh", "rfp"])
    assert result.exit_code != 0


def test_integration_registry_describe_delete_noninteractive(
    fleet_dir, stdin_not_tty
) -> None:
    _create_integration("idd")
    r = runner.invoke(app, ["integration", "registry", "describe", "idd"])
    assert r.exit_code == 0
    r = runner.invoke(
        app, ["integration", "registry", "delete", "idd", "--yes"]
    )
    assert r.exit_code == 0


def test_skill_registry_describe_noninteractive(fleet_dir, stdin_not_tty) -> None:
    listing = runner.invoke(app, ["skill", "registry", "get", "-o", "name"])
    refs = [
        line.split("/", 1)[1]
        for line in listing.output.strip().splitlines()
        if "/" in line
    ]
    assert refs, "expected at least one skill in catalog"
    r = runner.invoke(app, ["skill", "registry", "describe", refs[0]])
    assert r.exit_code == 0


def test_mcp_registry_describe_noninteractive(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(app, ["mcp", "registry", "describe", "foo"])
    assert result.exit_code == 0
    assert "Not implemented" in result.output
