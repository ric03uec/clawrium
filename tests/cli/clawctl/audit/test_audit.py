"""Tests for `clawctl audit` — the operator audit-trail subcommand.

These tests exercise the Typer surface end-to-end. The on-disk log
location is redirected via $CLAWRIUM_CONFIG_HOME so each test runs in
isolation in a tmp dir.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import pytest
from typer.testing import CliRunner

from clawrium.cli import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def audit_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the audit log root to a tmp dir.

    Also clears any session-id env the host machine might have set, so
    tests that rely on the env-var path start from a clean slate.
    """
    monkeypatch.setenv("CLAWRIUM_CONFIG_HOME", str(tmp_path / "clawrium"))
    monkeypatch.delenv("CLAWCTL_AUDIT_SESSION_ID", raising=False)
    return tmp_path / "clawrium" / "changelog"


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _single_log_file(audit_home: Path) -> Path:
    files = sorted(audit_home.glob("*.jsonl"))
    assert len(files) == 1, f"expected 1 log file, found {[f.name for f in files]}"
    return files[0]


# ---------------------------------------------------------------------------
# log
# ---------------------------------------------------------------------------

def test_log_writes_schema_v1_entry(audit_home: Path) -> None:
    result = runner.invoke(
        app,
        ["audit", "log", "clawctl agent start a1", "--result", "success", "--notes", "ok"],
    )
    assert result.exit_code == 0, result.output
    entries = _read_jsonl(_single_log_file(audit_home))
    assert len(entries) == 1
    e = entries[0]
    assert e["type"] == "clawctl_command"
    assert e["actor"] == "agent"
    assert e["action"] == "clawctl agent start a1"
    assert e["result"] == "success"
    assert e["notes"] == "ok"
    # uuid is a uuid4 string
    assert isinstance(e["uuid"], str) and len(e["uuid"]) == 36
    # ms-precision timestamp
    assert e["timestamp"].endswith("Z") and "." in e["timestamp"]
    # version block
    assert e["version"]["audit"] == "1"
    assert "clawctl" in e["version"]
    # cwd captured
    assert isinstance(e["cwd"], str) and e["cwd"]
    # session/parent default to null
    assert e["session_id"] is None
    assert e["parent_uuid"] is None


def test_log_actor_user_is_recorded(audit_home: Path) -> None:
    result = runner.invoke(
        app,
        ["audit", "log", "manual clawctl host create 1.2.3.4", "--result", "success", "--actor", "user"],
    )
    assert result.exit_code == 0, result.output
    e = _read_jsonl(_single_log_file(audit_home))[0]
    assert e["actor"] == "user"


def test_log_rejects_invalid_result(audit_home: Path) -> None:
    result = runner.invoke(app, ["audit", "log", "x", "--result", "bogus"])
    assert result.exit_code != 0
    assert "--result must be one of" in result.output


def test_log_rejects_invalid_actor(audit_home: Path) -> None:
    result = runner.invoke(
        app,
        ["audit", "log", "x", "--result", "success", "--actor", "bot"],
    )
    assert result.exit_code != 0
    assert "--actor must be one of" in result.output


def test_log_print_uuid_emits_only_uuid(audit_home: Path) -> None:
    result = runner.invoke(
        app,
        ["audit", "log", "x", "--result", "success", "--print-uuid"],
    )
    assert result.exit_code == 0, result.output
    # Output is exactly one uuid line, no "logged ->" prefix.
    line = result.output.strip()
    assert len(line) == 36, repr(line)
    entry = _read_jsonl(_single_log_file(audit_home))[0]
    assert entry["uuid"] == line


def test_log_parent_uuid_is_recorded(audit_home: Path) -> None:
    parent_run = runner.invoke(
        app, ["audit", "log", "configure", "--result", "success", "--print-uuid"]
    )
    parent_uuid = parent_run.output.strip()

    child_run = runner.invoke(
        app,
        ["audit", "log", "start", "--result", "success", "--parent-uuid", parent_uuid],
    )
    assert child_run.exit_code == 0, child_run.output

    entries = _read_jsonl(_single_log_file(audit_home))
    assert len(entries) == 2
    assert entries[0]["uuid"] == parent_uuid
    assert entries[1]["parent_uuid"] == parent_uuid


def test_log_session_id_from_env(audit_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAWCTL_AUDIT_SESSION_ID", "11111111-2222-3333-4444-555555555555")
    result = runner.invoke(app, ["audit", "log", "x", "--result", "success"])
    assert result.exit_code == 0, result.output
    e = _read_jsonl(_single_log_file(audit_home))[0]
    assert e["session_id"] == "11111111-2222-3333-4444-555555555555"


def test_log_explicit_session_id_overrides_env(audit_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAWCTL_AUDIT_SESSION_ID", "from-env")
    result = runner.invoke(
        app,
        ["audit", "log", "x", "--result", "success", "--session-id", "explicit"],
    )
    assert result.exit_code == 0
    e = _read_jsonl(_single_log_file(audit_home))[0]
    assert e["session_id"] == "explicit"


# ---------------------------------------------------------------------------
# show / tail / stats
# ---------------------------------------------------------------------------

def _seed(audit_home: Path, *args: Iterable[str]) -> None:
    for cmd in args:
        result = runner.invoke(app, list(cmd))
        assert result.exit_code == 0, result.output


def test_show_filter_by_result(audit_home: Path) -> None:
    _seed(
        audit_home,
        ["audit", "log", "clawctl agent start a1", "--result", "success"],
        ["audit", "log", "clawctl agent stop a2", "--result", "failure", "--notes", "broken"],
        ["audit", "log", "clawctl agent sync a3", "--result", "success"],
    )
    result = runner.invoke(app, ["audit", "show", "--result", "failure"])
    assert result.exit_code == 0
    assert "clawctl agent stop a2" in result.output
    assert "clawctl agent start a1" not in result.output
    assert "clawctl agent sync a3" not in result.output


def test_show_filter_by_session_id(audit_home: Path) -> None:
    _seed(
        audit_home,
        ["audit", "log", "alpha", "--result", "success", "--session-id", "S1"],
        ["audit", "log", "beta", "--result", "success", "--session-id", "S2"],
        ["audit", "log", "gamma", "--result", "success", "--session-id", "S1"],
    )
    result = runner.invoke(app, ["audit", "show", "--session-id", "S1", "--json"])
    assert result.exit_code == 0
    lines = [ln for ln in result.output.splitlines() if ln.strip()]
    actions = [json.loads(ln)["action"] for ln in lines]
    assert sorted(actions) == ["alpha", "gamma"]


def test_show_grep_matches_action_and_notes(audit_home: Path) -> None:
    _seed(
        audit_home,
        ["audit", "log", "foo", "--result", "success", "--notes", "deploy myassistant"],
        ["audit", "log", "bar", "--result", "success"],
        ["audit", "log", "myassistant boot", "--result", "success"],
    )
    result = runner.invoke(app, ["audit", "show", "--grep", "myassistant", "--json"])
    assert result.exit_code == 0
    lines = [ln for ln in result.output.splitlines() if ln.strip()]
    assert len(lines) == 2
    actions = sorted(json.loads(ln)["action"] for ln in lines)
    assert actions == ["foo", "myassistant boot"]


def test_show_last_n_returns_tail_after_filters(audit_home: Path) -> None:
    _seed(
        audit_home,
        ["audit", "log", "a", "--result", "success"],
        ["audit", "log", "b", "--result", "success"],
        ["audit", "log", "c", "--result", "success"],
        ["audit", "log", "d", "--result", "success"],
    )
    result = runner.invoke(app, ["audit", "show", "--last", "2", "--json"])
    assert result.exit_code == 0
    actions = [json.loads(ln)["action"] for ln in result.output.splitlines() if ln.strip()]
    assert actions == ["c", "d"]


def test_tail_default_returns_recent(audit_home: Path) -> None:
    _seed(
        audit_home,
        ["audit", "log", "first", "--result", "success"],
        ["audit", "log", "second", "--result", "success"],
    )
    result = runner.invoke(app, ["audit", "tail"])
    assert result.exit_code == 0
    out = result.output
    assert "first" in out and "second" in out
    # second must come after first
    assert out.index("first") < out.index("second")


def test_stats_summarises_by_actor_result_verb(audit_home: Path) -> None:
    _seed(
        audit_home,
        ["audit", "log", "clawctl agent start a1", "--result", "success"],
        ["audit", "log", "clawctl agent stop a1", "--result", "failure", "--notes", "x"],
        ["audit", "log", "clawctl host create 1.2.3.4", "--actor", "user", "--result", "success"],
    )
    result = runner.invoke(app, ["audit", "stats", "--top", "5"])
    assert result.exit_code == 0
    out = result.output
    assert "Total entries:     3" in out
    assert "'agent': 2" in out and "'user': 1" in out
    assert "'success': 2" in out and "'failure': 1" in out
    assert "clawctl agent" in out
    assert "clawctl host" in out


def test_stats_on_empty_trail_returns_zero(audit_home: Path) -> None:
    result = runner.invoke(app, ["audit", "stats"])
    assert result.exit_code == 0
    assert "Total entries:     0" in result.output


def test_show_on_empty_trail_prints_nothing(audit_home: Path) -> None:
    result = runner.invoke(app, ["audit", "show"])
    assert result.exit_code == 0
    assert result.output.strip() == ""


# ---------------------------------------------------------------------------
# session / path
# ---------------------------------------------------------------------------

def test_session_new_emits_uuid4(audit_home: Path) -> None:
    result = runner.invoke(app, ["audit", "session", "new"])
    assert result.exit_code == 0
    sid = result.output.strip()
    assert len(sid) == 36
    # Calling twice gives different ids.
    second = runner.invoke(app, ["audit", "session", "new"]).output.strip()
    assert sid != second


def test_path_prints_changelog_dir(audit_home: Path) -> None:
    result = runner.invoke(app, ["audit", "path"])
    assert result.exit_code == 0
    assert result.output.strip().endswith("clawrium/changelog")


# ---------------------------------------------------------------------------
# Read tolerance
# ---------------------------------------------------------------------------

def test_iter_entries_skips_malformed_lines(audit_home: Path) -> None:
    """A corrupt line must not block reading the rest of the trail."""
    # Seed two good entries.
    _seed(
        audit_home,
        ["audit", "log", "good1", "--result", "success"],
        ["audit", "log", "good2", "--result", "success"],
    )
    log_file = _single_log_file(audit_home)
    # Inject a malformed line between the good ones.
    raw = log_file.read_text().splitlines()
    log_file.write_text(raw[0] + "\n" + "{not-json\n" + raw[1] + "\n")

    result = runner.invoke(app, ["audit", "show", "--json"])
    assert result.exit_code == 0
    actions = [json.loads(ln)["action"] for ln in result.output.splitlines() if ln.strip()]
    assert actions == ["good1", "good2"]
