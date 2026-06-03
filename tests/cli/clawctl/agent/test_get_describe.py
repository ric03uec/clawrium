"""Tests for `clawctl agent get` and `clawctl agent describe`."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

from clawrium.cli import app
from clawrium.cli.clawctl.agent._shared import _first_provider

runner = CliRunner()


def _patch_fleet_agent(fleet_dir, mutator) -> None:
    """Load hosts.json, apply mutator to the wise-hypatia agent record, save."""
    hosts_path = Path(fleet_dir) / "hosts.json"
    hosts = json.loads(hosts_path.read_text())
    mutator(hosts[0]["agents"]["openclaw"])
    hosts_path.write_text(json.dumps(hosts, indent=2))


def test_get_default_columns(fleet_dir) -> None:
    result = runner.invoke(app, ["agent", "get"])
    assert result.exit_code == 0
    for col in ("NAME", "TYPE", "HOST", "PROVIDER", "STATUS", "AGE"):
        assert col in result.output, f"missing column: {col}"
    assert "wise-hypatia" in result.output


def test_get_wide_includes_extra_columns(fleet_dir) -> None:
    result = runner.invoke(app, ["agent", "get", "-o", "wide"])
    assert result.exit_code == 0
    for col in ("ADDRESS", "PORT", "VERSION", "INSTALLED"):
        assert col in result.output, f"missing wide column: {col}"


def test_get_json_round_trip_yaml(fleet_dir) -> None:
    json_out = runner.invoke(app, ["agent", "get", "-o", "json"])
    yaml_out = runner.invoke(app, ["agent", "get", "-o", "yaml"])
    assert json_out.exit_code == 0
    assert yaml_out.exit_code == 0
    assert json.loads(json_out.output) == yaml.safe_load(yaml_out.output)


def test_get_name_format(fleet_dir) -> None:
    result = runner.invoke(app, ["agent", "get", "-o", "name"])
    assert result.exit_code == 0
    lines = [line for line in result.output.strip().split("\n") if line]
    assert lines == ["agent/wise-hypatia"]


def test_get_selector_filters_via_host_labels(fleet_dir) -> None:
    # `kevin` (env=dev) has no agents, `wolf-i` (env=prod) has one.
    prod = runner.invoke(app, ["agent", "get", "-l", "env=prod", "-o", "name"])
    dev = runner.invoke(app, ["agent", "get", "-l", "env=dev", "-o", "name"])
    assert "agent/wise-hypatia" in prod.output
    assert "agent/wise-hypatia" not in dev.output


def test_describe_includes_onboarding(fleet_dir) -> None:
    result = runner.invoke(app, ["agent", "describe", "wise-hypatia"])
    assert result.exit_code == 0
    assert "Onboarding:" in result.output
    assert "providers" in result.output
    assert "validate" in result.output


def test_describe_renders_completed_stage_status(fleet_dir) -> None:
    # Regression: describe.py read `info.get("state")` while stage records
    # are written by core/onboarding.py:complete_stage under `status`.
    # Every completed agent rendered every stage as "pending". The fixture
    # also had `state`, so no test caught the mismatch end-to-end until
    # both sides were aligned on the real key (`status`).
    result = runner.invoke(app, ["agent", "describe", "wise-hypatia"])
    assert result.exit_code == 0
    onboarding_block = result.output.split("Onboarding:", 1)[1]
    assert "complete" in onboarding_block
    assert "skipped" in onboarding_block
    # Should NOT show pending for a stage that has a recorded status.
    # (Empty stages would still default to pending; the fixture has none.)
    pending_count = onboarding_block.lower().count("pending")
    assert pending_count == 0, (
        f"onboarding block reported {pending_count} pending stage(s) but "
        f"fixture has all stages with explicit status; block was:\n{onboarding_block}"
    )


def test_describe_unknown_agent_errors(fleet_dir) -> None:
    result = runner.invoke(app, ["agent", "describe", "nope"])
    assert result.exit_code != 0
    assert "not found" in result.output


def test_describe_json(fleet_dir) -> None:
    result = runner.invoke(app, ["agent", "describe", "wise-hypatia", "-o", "json"])
    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert parsed[0]["name"] == "wise-hypatia"
    assert parsed[0]["kind"] == "agent"


# ---------------------------------------------------------------------------
# _first_provider read coverage
#
# Single source of truth: provider state is read from EXACTLY one place —
# tier-1 `claw_record["providers"]` (the attach list). There is no fallback
# to the tier-2 `config.provider` materialization or the vestigial tier-3
# `config.providers` plural. This aligns the display reader with
# build_render_inputs (render.py), which raises when the same tier-1 list is
# empty. An agent whose provider lives only in `config.provider` reads as
# "no provider attached" and must be fixed with `clawctl agent provider
# attach <provider> --agent <name>`.
# ---------------------------------------------------------------------------


def test_first_provider_prefers_attach_list_string():
    record = {
        "providers": ["clawrium-glm51"],
        "config": {"provider": {"name": "ignored-stale-value"}},
    }
    assert _first_provider(record) == "clawrium-glm51"


def test_first_provider_prefers_attach_list_dict_entry():
    record = {"providers": [{"name": "clawrium-glm51", "type": "openrouter"}]}
    assert _first_provider(record) == "clawrium-glm51"


def test_first_provider_ignores_materialized_config_provider():
    # tier-2 `config.provider` is the singular dict written by
    # sync_agent / configure_agent as the Ansible render payload. It is
    # NOT a read source: with no tier-1 attach list, _first_provider
    # returns None regardless of config.provider.
    record = {"config": {"provider": {"name": "clawrium-glm51"}}}
    assert _first_provider(record) is None


def test_first_provider_empty_attach_list_does_not_use_materialization():
    record = {
        "providers": [],
        "config": {"provider": {"name": "clawrium-glm51"}},
    }
    assert _first_provider(record) is None


def test_first_provider_returns_none_when_nothing_present():
    assert _first_provider({}) is None
    assert _first_provider({"config": {}}) is None
    assert _first_provider({"config": {"provider": {}}}) is None


def test_first_provider_ignores_vestigial_plural_path():
    # tier-3 `config.providers` (plural) was a vestigial reader. It is no
    # longer consulted; only the tier-1 attach list resolves.
    record = {"config": {"providers": {"legacy-name": {"type": "ollama"}}}}
    assert _first_provider(record) is None


def test_first_provider_dict_entry_without_name_returns_none():
    # A dict attach-list entry missing the `name` key has no resolvable
    # tier-1 provider; with no fallback this reads as None.
    record = {
        "providers": [{"type": "openrouter"}],  # no `name`
        "config": {"provider": {"name": "clawrium-glm51"}},
    }
    assert _first_provider(record) is None


def test_first_provider_empty_string_attach_entry_returns_none():
    # An empty string in the attach list is not a valid provider name and
    # does not fall through to any other tier.
    record = {
        "providers": [""],
        "config": {"provider": {"name": "clawrium-glm51"}},
    }
    assert _first_provider(record) is None


def test_first_provider_tier2_only_record_reads_as_none():
    # Regression for the provider-tier reader asymmetry bug: a record
    # shaped like vand/doppio before tier-1 back-fill — no top-level
    # `providers`, provider only in `config.provider` — must read as
    # None so the display agrees with the render/drift path that raises
    # AgentConfigError for the same shape.
    record = {
        "config": {
            "provider": {
                "name": "esper-bedrock",
                "type": "bedrock",
                "endpoint": "",
                "default_model": "zai.glm-5",
            }
        }
    }
    assert _first_provider(record) is None


def test_first_provider_never_synced_agent_shape():
    # Matches the shape install.py writes before any sync runs:
    # `{"config": {"gateway": {...}}}` — no `provider` key at all.
    # _first_provider must return None (renders as `-`) without
    # raising.
    record = {"config": {"gateway": {"url": "http://localhost:40000"}}}
    assert _first_provider(record) is None


# ---------------------------------------------------------------------------
# Onboarding stage status rendering (B2 + W3 coverage)
# ---------------------------------------------------------------------------


# Stage status `status` primary read — B2 discriminating tests
# ---------------------------------------------------------------------------


def test_describe_stage_status_key_wins_over_state_key(fleet_dir) -> None:
    # B2: when both `status` and `state` are present, `status` must win.
    def mutate(agent):
        agent["onboarding"]["stages"]["providers"] = {
            "status": "complete",
            "state": "legacy-should-be-ignored",
        }

    _patch_fleet_agent(fleet_dir, mutate)

    result = runner.invoke(app, ["agent", "describe", "wise-hypatia"])
    assert result.exit_code == 0
    onboarding_block = result.output.split("Onboarding:", 1)[1]
    assert "legacy-should-be-ignored" not in onboarding_block
    providers_line = next(
        line for line in onboarding_block.splitlines() if "providers" in line
    )
    assert "complete" in providers_line


def test_describe_stage_status_only_no_state_fallback(fleet_dir) -> None:
    # W-B (iter-2): if `info.get("status")` is removed from describe.py,
    # this test fails — the `state` fallback returns None, default
    # "pending" wins, and the assertion below catches the regression.
    # Discriminates the primary-read failure mode without relying on
    # the two-key fixture or the empty-dict fixture (both of which
    # would silently pass with only the `state` fallback).
    def mutate(agent):
        agent["onboarding"]["stages"]["providers"] = {"status": "complete"}

    _patch_fleet_agent(fleet_dir, mutate)

    result = runner.invoke(app, ["agent", "describe", "wise-hypatia"])
    assert result.exit_code == 0
    onboarding_block = result.output.split("Onboarding:", 1)[1]
    providers_line = next(
        line for line in onboarding_block.splitlines() if "providers" in line
    )
    assert "complete" in providers_line
    assert "pending" not in providers_line


def test_describe_stage_missing_status_defaults_to_pending(fleet_dir) -> None:
    # B2: a stage record with neither `status` nor `state` falls back
    # to the default `pending`.
    def mutate(agent):
        agent["onboarding"]["stages"]["identity"] = {}

    _patch_fleet_agent(fleet_dir, mutate)

    result = runner.invoke(app, ["agent", "describe", "wise-hypatia"])
    assert result.exit_code == 0
    onboarding_block = result.output.split("Onboarding:", 1)[1]
    identity_line = next(
        line for line in onboarding_block.splitlines() if "identity" in line
    )
    assert "pending" in identity_line


# ---------------------------------------------------------------------------
# Backward-compatibility shim — `state`-key fallback for handwritten records
# ---------------------------------------------------------------------------


def test_describe_stage_state_key_fallback(fleet_dir) -> None:
    # W3 (iter-1): the `or info.get("state")` shim is kept for
    # handwritten / third-party records that use the old key shape.
    # Make it live and intentional by asserting it renders correctly
    # when only `state` is present. This is NOT a B2 discriminator —
    # see `test_describe_stage_status_only_no_state_fallback` for that.
    def mutate(agent):
        agent["onboarding"]["stages"]["validate"] = {"state": "complete"}

    _patch_fleet_agent(fleet_dir, mutate)

    result = runner.invoke(app, ["agent", "describe", "wise-hypatia"])
    assert result.exit_code == 0
    onboarding_block = result.output.split("Onboarding:", 1)[1]
    validate_line = next(
        line for line in onboarding_block.splitlines() if "validate" in line
    )
    assert "complete" in validate_line


# ---------------------------------------------------------------------------
# Provider column CLI-level coverage
# ---------------------------------------------------------------------------


def test_describe_provider_line_renders_attach_list_name(fleet_dir) -> None:
    # CLI-level coverage for the Provider column.
    def mutate(agent):
        agent["providers"] = ["clawrium-glm51"]

    _patch_fleet_agent(fleet_dir, mutate)

    result = runner.invoke(app, ["agent", "describe", "wise-hypatia"])
    assert result.exit_code == 0
    provider_line = next(
        line for line in result.output.splitlines() if line.startswith("Provider:")
    )
    assert "clawrium-glm51" in provider_line


# ---------------------------------------------------------------------------
# Tier-3 vestigial path is no longer read (single-source consolidation)
# ---------------------------------------------------------------------------


def test_first_provider_tier3_list_dict_without_name_returns_none():
    record = {"config": {"providers": [{"type": "ollama"}]}}
    assert _first_provider(record) is None


def test_first_provider_tier3_list_none_entry_returns_none():
    record = {"config": {"providers": [None]}}
    assert _first_provider(record) is None


def test_first_provider_tier3_list_int_entry_returns_none():
    record = {"config": {"providers": [42]}}
    assert _first_provider(record) is None


# ---------------------------------------------------------------------------
# Type-safety on tier-1 dict `name` value
# ---------------------------------------------------------------------------


def test_first_provider_dict_name_value_is_non_string_returns_none():
    # A dict attach-list entry whose `name` is itself a dict is not a
    # valid provider name; with no fallback this reads as None.
    record = {
        "providers": [{"name": {"nested": "bad"}}],
        "config": {"provider": {"name": "clawrium-glm51"}},
    }
    assert _first_provider(record) is None


# ---------------------------------------------------------------------------
# Format validation on tier-1 string entries (defense-in-depth)
# ---------------------------------------------------------------------------


def test_first_provider_string_attach_with_markup_returns_none():
    # A tier-1 attach entry containing Rich/markdown markup (`[bold]x[/]`)
    # does not match PROVIDER_NAME_PATTERN; with no fallback it reads as
    # None so a malformed attach record cannot inject characters into the
    # PROVIDER column.
    record = {
        "providers": ["[bold]atk[/]"],
        "config": {"provider": {"name": "clawrium-glm51"}},
    }
    assert _first_provider(record) is None


def test_first_provider_string_attach_with_invalid_chars_returns_none():
    # Pattern rejects names with `/`, `:`, etc.
    record = {
        "providers": ["evil/path"],
        "config": {"provider": {"name": "clawrium-glm51"}},
    }
    assert _first_provider(record) is None


# ---------------------------------------------------------------------------
# Tier-1 pattern boundary coverage
# ---------------------------------------------------------------------------


def test_first_provider_accept_64_char_name_is_valid():
    # PROVIDER_NAME_PATTERN's `{0,63}` quantifier allows up to 64 chars
    # total (1 leading letter + 63 trailing). Exercise the boundary so a
    # future tightening (e.g. `{0,62}`) would be caught by test failure
    # rather than silent rejection at runtime.
    name_64 = "a" + "x" * 63
    assert len(name_64) == 64
    assert _first_provider({"providers": [name_64]}) == name_64


def test_first_provider_accept_65_char_name_returns_none():
    # One character over the limit must read as None (no fallback).
    name_65 = "a" + "x" * 64
    assert len(name_65) == 65
    record = {
        "providers": [name_65],
        "config": {"provider": {"name": "clawrium-glm51"}},
    }
    assert _first_provider(record) is None


def test_describe_stage_empty_status_string_does_not_use_state_shim(
    fleet_dir,
) -> None:
    # W-N-2: explicit `is not None` guard means `{"status": ""}`
    # renders "pending" (status key present, value empty) rather than
    # silently falling through to `state` (which would render
    # "complete"). Documents the intent the leader requested in
    # ATX iter-3.
    def mutate(agent):
        agent["onboarding"]["stages"]["validate"] = {
            "status": "",
            "state": "complete-from-state-shim",
        }

    _patch_fleet_agent(fleet_dir, mutate)

    result = runner.invoke(app, ["agent", "describe", "wise-hypatia"])
    assert result.exit_code == 0
    onboarding_block = result.output.split("Onboarding:", 1)[1]
    validate_line = next(
        line for line in onboarding_block.splitlines() if "validate" in line
    )
    # status key present but empty → renders pending, NOT state value
    assert "complete-from-state-shim" not in validate_line
    assert "pending" in validate_line
