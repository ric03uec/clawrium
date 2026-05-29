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
