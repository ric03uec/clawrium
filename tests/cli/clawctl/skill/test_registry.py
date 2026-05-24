"""Tests for `clawctl skill registry` read-only catalog access."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from clawrium.cli import app

runner = CliRunner()


def test_get_lists_skills(fleet_dir) -> None:
    result = runner.invoke(app, ["skill", "registry", "get"])
    assert result.exit_code == 0, result.output
    # The bundled `skills/` catalog contains at least one `clawrium/<name>` skill.
    assert "NAME" in result.output
    assert "REGISTRY" in result.output


def test_get_with_registry_selector(fleet_dir) -> None:
    result = runner.invoke(app, ["skill", "registry", "get", "-l", "registry=clawrium"])
    assert result.exit_code == 0, result.output
    # Every line after the header should be a clawrium-namespaced ref.
    body_lines = result.output.strip().splitlines()[1:]
    for line in body_lines:
        if line:
            assert line.startswith("clawrium/"), line


def test_get_with_unknown_registry_filter_returns_empty(fleet_dir) -> None:
    result = runner.invoke(
        app, ["skill", "registry", "get", "-l", "registry=no-such-registry"]
    )
    # Filter via valid registries hits InvalidSkillRef path → exit non-zero.
    assert result.exit_code != 0


def test_get_json_emits_array(fleet_dir) -> None:
    result = runner.invoke(app, ["skill", "registry", "get", "-o", "json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, list)


def test_no_create_subcommand_exists(fleet_dir) -> None:
    """Skill registry must be read-only — `create` is not exposed."""
    result = runner.invoke(app, ["skill", "registry", "--help"])
    assert result.exit_code == 0
    assert "create" not in result.output


def test_describe_known(fleet_dir) -> None:
    listing = runner.invoke(app, ["skill", "registry", "get", "-o", "name"])
    refs = [line for line in listing.output.strip().splitlines() if line]
    assert refs, "skills catalog should be non-empty"
    # Each entry from `-o name` is `skill/<registry>/<name>`; drop the kind prefix.
    ref = refs[0].split("/", 1)[1]
    result = runner.invoke(app, ["skill", "registry", "describe", ref])
    assert result.exit_code == 0, result.output


def test_describe_bare_name_rejected(fleet_dir) -> None:
    result = runner.invoke(app, ["skill", "registry", "describe", "tdd"])
    assert result.exit_code != 0
