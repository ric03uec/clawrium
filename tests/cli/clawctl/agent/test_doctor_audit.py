"""Schema gate for `tests/fixtures/audit_2026_05_29.json` — F4 of #555.

The fixture is the reference baseline for `clawctl agent doctor`
against the 10 audited agents from issue #555. This test pins the
fixture's shape (every row has name + type + expected_status) so a
future edit cannot silently drop a row or change the expected
verdict without a failing test.

The end-to-end "doctor's output matches the fixture verdict" assertion
needs synthetic providers.json / channels.json / integrations.json /
secrets.json + hosts.json fixtures matching each agent's `shape`,
which is wired in the F5 migration follow-up (parent #555). Until
then, this schema gate is what protects the fixture from drift.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from clawrium.cli import app
from clawrium.core.render import (
    AgentConfigError,
    ProviderInputs,
    RenderInputs,
    RenderedFiles,
)


_runner = CliRunner()


FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "audit_2026_05_29.json"
)


def test_audit_fixture_loads() -> None:
    assert FIXTURE.exists(), f"missing fixture: {FIXTURE}"
    payload = json.loads(FIXTURE.read_text())
    assert "_meta" in payload
    assert "agents" in payload
    assert len(payload["agents"]) == 10, (
        "audit_2026_05_29.json must enumerate the 10 reference agents from #555"
    )


def test_audit_fixture_rows_have_required_fields() -> None:
    payload = json.loads(FIXTURE.read_text())
    for row in payload["agents"]:
        assert "name" in row
        assert "type" in row
        assert row["type"] in {"hermes", "zeroclaw", "openclaw"}
        assert row["expected_status"] in {"ok", "broken"}
        if row["expected_status"] == "broken":
            assert "expected_error_contains" in row, (
                f"broken row {row['name']!r} must declare expected_error_contains"
            )


def test_audit_fixture_names_match_issue_555_table() -> None:
    payload = json.loads(FIXTURE.read_text())
    names = {row["name"] for row in payload["agents"]}
    expected = {
        "wolf-i",
        "clawrium-d01",
        "espresso",
        "nemotron-alpha",
        "nemotron-beta",
        "clawctl-demo",
        "h1",
        "h2",
        "clawctl-mac-demo",
        "maurice",
    }
    assert names == expected


# ---------------------------------------------------------------------------
# End-to-end doctor verdict assertions (ATX iter-1 B6).
#
# A full per-row synthetic store fixture would duplicate F5's migration
# scaffolding (parent #555 DoD). For now we cover the two representative
# rows whose verdicts encode the core regression #555 was filed against:
# the reference baseline ("clawrium-d01" → ok) and the fully-wiped
# survivor ("maurice" → broken with provider-missing error). This pins
# the doctor's broken-vs-ok classification against the canonical
# expectations from the audit table. The remaining 8 rows stay as
# schema-pinned baseline rows; the F5 follow-up replaces this gap.
# ---------------------------------------------------------------------------

def _fixture_row(name: str) -> dict:
    payload = json.loads(FIXTURE.read_text())
    for row in payload["agents"]:
        if row["name"] == name:
            return row
    raise KeyError(name)


def test_doctor_matches_audit_verdict_clawrium_d01(fleet_dir, monkeypatch) -> None:
    """`clawrium-d01` is the baseline. doctor must return ok."""
    row = _fixture_row("clawrium-d01")
    assert row["expected_status"] == "ok"

    from clawrium.cli.clawctl.agent import doctor as doctor_mod

    inputs = RenderInputs(
        agent_name="wise-hypatia",
        agent_type=row["type"],  # zeroclaw
        provider=ProviderInputs(
            name="openrouter",
            type="openrouter",
            default_model="openai/gpt-5",
            api_key="sk-xxx",
        ),
    )
    files = RenderedFiles(files={".zeroclaw/config.toml": "ok\n"})

    monkeypatch.setattr(doctor_mod, "build_render_inputs", lambda n: inputs)
    monkeypatch.setattr(doctor_mod, "render_zeroclaw", lambda i: files)

    result = _runner.invoke(app, ["agent", "doctor", "wise-hypatia", "-o", "json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload[0]["status"] == row["expected_status"]


def test_doctor_matches_audit_verdict_maurice(fleet_dir, monkeypatch) -> None:
    """`maurice` is fully wiped. doctor must return broken with provider error."""
    row = _fixture_row("maurice")
    assert row["expected_status"] == "broken"
    assert row["expected_error_contains"] == "provider"

    from clawrium.cli.clawctl.agent import doctor as doctor_mod

    def _raise(name: str):
        raise AgentConfigError(
            f"agent {name!r} has no provider attached; "
            f"run `clawctl agent provider attach <provider> --agent {name}` first"
        )

    monkeypatch.setattr(doctor_mod, "build_render_inputs", _raise)

    result = _runner.invoke(app, ["agent", "doctor", "wise-hypatia", "-o", "json"])
    assert result.exit_code != 0
    arr_end = result.output.rfind("]")
    payload = json.loads(result.output[: arr_end + 1])
    assert payload[0]["status"] == row["expected_status"]
    assert row["expected_error_contains"] in payload[0]["error"]
