"""Tests for #583 fixes — the configure-path observability and
pre-render plumbing that lets zeroclaw and openclaw configure
without workarounds.

Two layers:
  - `_summarize_ansible_configure_failure` — pure helper extracted from
    configure_agent so the error-string mapping can be exercised
    directly without spinning a real Ansible job.
  - The zeroclaw filter plugin must produce byte-for-byte the same
    output as the canonical Python `_toml_escape`, otherwise the two
    render paths drift again and #555/#583 are reopened on the next
    configure.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from clawrium.core.lifecycle import _summarize_ansible_configure_failure


def _result(
    *,
    status: str = "failed",
    rc: int = 2,
    events: list | None = None,
    stdout: str = "",
    stderr: str = "",
):
    r = MagicMock()
    r.status = status
    r.rc = rc
    r.events = list(events or [])
    stdout_obj = MagicMock()
    stdout_obj.read = MagicMock(return_value=stdout)
    r.stdout = stdout_obj
    stderr_obj = MagicMock()
    stderr_obj.read = MagicMock(return_value=stderr)
    r.stderr = stderr_obj
    return r


# ---------------------------------------------------------------------------
# runner_on_failed with uncensored res → task name + underlying detail
# ---------------------------------------------------------------------------


def test_task_failure_with_msg_surfaces_task_name_and_msg():
    error = _summarize_ansible_configure_failure(
        _result(
            events=[
                {
                    "event": "runner_on_failed",
                    "event_data": {
                        "task": "Render ~/.zeroclaw/config.toml from template",
                        "res": {
                            "msg": "Syntax error in template: No filter named 'toq'."
                        },
                    },
                }
            ]
        ),
        log_dir="/tmp/x",
    )
    assert "Render ~/.zeroclaw/config.toml from template" in error
    assert "No filter named 'toq'" in error


def test_task_failure_with_stderr_only_surfaces_stderr():
    error = _summarize_ansible_configure_failure(
        _result(
            events=[
                {
                    "event": "runner_on_failed",
                    "event_data": {
                        "task": "Restart service",
                        "res": {"stderr": "Job for foo.service failed"},
                    },
                }
            ]
        ),
        log_dir="/tmp/x",
    )
    assert "Restart service" in error
    assert "Job for foo.service failed" in error


def test_task_failure_msg_None_falls_through_to_stderr():
    """ATX #445 iter-3 NW4 regression: a `{"msg": None}` entry must
    not short-circuit error_msg to None; the reporter must fall
    through to `stderr` before bailing."""
    error = _summarize_ansible_configure_failure(
        _result(
            events=[
                {
                    "event": "runner_on_failed",
                    "event_data": {
                        "task": "Verify probe",
                        "res": {"msg": None, "stderr": "probe got 500"},
                    },
                }
            ]
        ),
        log_dir="/tmp/x",
    )
    assert error.startswith("task 'Verify probe': ")
    assert "probe got 500" in error
    assert "None" not in error


def test_uncensored_failure_after_censored_still_picks_uncensored():
    """A no_log task that censors first, then a normal task fails —
    the reporter must surface the second (uncensored) one, NOT the
    censored hint. Otherwise operators would see the no_log hint
    even when a clear actionable error existed."""
    error = _summarize_ansible_configure_failure(
        _result(
            events=[
                {
                    "event": "runner_on_failed",
                    "event_data": {
                        "task": "no_log task",
                        "res": {"censored": "no_log: true"},
                    },
                },
                {
                    "event": "runner_on_failed",
                    "event_data": {
                        "task": "loud task",
                        "res": {"msg": "real error here"},
                    },
                },
            ]
        ),
        log_dir="/tmp/x",
    )
    assert "loud task" in error
    assert "real error here" in error
    assert "no_log: true" not in error


# ---------------------------------------------------------------------------
# All-censored fallback: surface task name + ANSIBLE_NO_LOG hint
# ---------------------------------------------------------------------------


def test_all_censored_surfaces_task_name_and_hint():
    """#583 core fix: when every runner_on_failed event was censored,
    the operator gets the failing task name + a hint on how to see
    the underlying error. Previously: useless `\"failed\"` literal."""
    error = _summarize_ansible_configure_failure(
        _result(
            events=[
                {
                    "event": "runner_on_failed",
                    "event_data": {
                        "task": "Render ~/.zeroclaw/config.toml from template",
                        "res": {
                            "censored": (
                                "the output has been hidden due to the fact "
                                "that 'no_log: true' was specified for this "
                                "result"
                            )
                        },
                    },
                }
            ]
        ),
        log_dir="/tmp/x",
    )
    assert "Render ~/.zeroclaw/config.toml from template" in error
    assert "no_log: true" in error
    assert "ANSIBLE_NO_LOG=False" in error


def test_censored_event_does_not_leak_bearer_into_hint():
    """The censored-skip preserves the original security invariant —
    a bearer token in `res.msg` of a censored event must NOT appear
    in the surfaced error even though we now surface the task name."""
    error = _summarize_ansible_configure_failure(
        _result(
            events=[
                {
                    "event": "runner_on_failed",
                    "event_data": {
                        "task": "Some sensitive task",
                        "res": {
                            "censored": "no_log: true",
                            "msg": "Bearer zc_LEAKED_xxxxxxxxxxxxxxxxxxxxx",
                            "stderr": "Bearer api_LEAKED_yyyyyyyyyyyyy",
                        },
                    },
                }
            ]
        ),
        log_dir="/tmp/x",
    )
    assert "zc_LEAKED" not in error
    assert "api_LEAKED" not in error
    # Task name is safe; hint is present.
    assert "Some sensitive task" in error


def test_all_censored_picks_first_task_name():
    """Multiple censored failures — surface the first one. The first
    failure usually causes the cascade; later censored tasks are
    typically downstream effects of the first."""
    error = _summarize_ansible_configure_failure(
        _result(
            events=[
                {
                    "event": "runner_on_failed",
                    "event_data": {
                        "task": "first task",
                        "res": {"censored": "x"},
                    },
                },
                {
                    "event": "runner_on_failed",
                    "event_data": {
                        "task": "second task",
                        "res": {"censored": "x"},
                    },
                },
            ]
        ),
        log_dir="/tmp/x",
    )
    assert "first task" in error
    assert "second task" not in error


# ---------------------------------------------------------------------------
# Pre-task failure: no runner_on_failed → surface stdout / recap
# ---------------------------------------------------------------------------


def test_pre_task_failure_with_stdout():
    """When ansible-runner fails BEFORE any task starts (playbook parse
    error, inventory load error), runner_on_failed events never fire.
    The reporter must read `result.stdout`."""
    error = _summarize_ansible_configure_failure(
        _result(
            events=[],
            stdout="ERROR! the playbook: configure.yaml could not be found",
            rc=2,
        ),
        log_dir="/tmp/x",
    )
    assert "before any task ran" in error
    assert "could not be found" in error
    assert "rc=2" in error


def test_pre_task_failure_with_recap_event():
    """When tasks ran but no runner_on_failed event fired (all task
    failures were inside loops emitting runner_item_on_failed only,
    or were no_log: true), `playbook_on_stats` still carries recap
    counts. Surface them."""
    error = _summarize_ansible_configure_failure(
        _result(
            events=[
                {
                    "event": "playbook_on_stats",
                    "event_data": {
                        "failures": {"192.168.1.36": 1},
                        "ok": {"192.168.1.36": 5},
                        "skipped": {"192.168.1.36": 2},
                    },
                }
            ]
        ),
        log_dir="/tmp/x",
    )
    assert "before any task ran" in error
    assert "recap" in error
    assert "192.168.1.36" in error


def test_pre_task_failure_falls_back_to_artifact_pointer():
    """Defensive: failed result with no events AND no output → at
    least give the operator the artifact log directory to dig into."""
    error = _summarize_ansible_configure_failure(
        _result(events=[], stdout="", stderr="", rc=1),
        log_dir="/some/log/dir",
    )
    assert "rc=1" in error
    assert "/some/log/dir" in error


def test_stdout_blob_trimmed_to_last_1024_bytes():
    """A 50KB stdout dump from a noisy playbook would flood the CLI.
    Reporter must trim to the tail 1KB so the actionable end of a
    traceback survives but the noise is dropped."""
    huge = ("noise\n" * 10000) + "REAL ERROR AT THE END\n"
    error = _summarize_ansible_configure_failure(
        _result(events=[], stdout=huge, rc=2),
        log_dir="/tmp/x",
    )
    # Tail content present; total length bounded.
    assert "REAL ERROR AT THE END" in error
    assert len(error) < 4096


def test_stdout_read_exception_falls_through_silently():
    """If result.stdout.read() raises (closed file, IOError), the
    reporter must not blow up — it should still emit the rc/status
    envelope so the operator gets _something_ actionable."""
    r = _result(events=[], rc=2)
    r.stdout.read = MagicMock(side_effect=IOError("closed"))
    r.stderr.read = MagicMock(side_effect=IOError("closed"))
    error = _summarize_ansible_configure_failure(r, log_dir="/tmp/x")
    assert "rc=2" in error


# ---------------------------------------------------------------------------
# Filter plugin parity: toq vs _toml_escape
# ---------------------------------------------------------------------------


def test_filter_plugin_toq_matches_python_toml_escape():
    """Whatever the canonical Python render's `_toml_escape` produces
    for a given input, the Ansible-side filter plugin must produce
    byte-for-byte the same string. If the two ever drift, sync and
    configure will write different config.toml bytes — exactly the
    dual-render hazard #583 closed."""
    import importlib.util

    repo_root = Path(__file__).resolve().parents[2]
    plugin_path = (
        repo_root
        / "src"
        / "clawrium"
        / "platform"
        / "registry"
        / "zeroclaw"
        / "playbooks"
        / "filter_plugins"
        / "clawrium_filters.py"
    )
    assert plugin_path.exists(), (
        f"filter plugin missing at {plugin_path} — #583 fix not landed"
    )
    spec = importlib.util.spec_from_file_location(
        "_test_clawrium_filters", plugin_path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    from clawrium.core.render import _toml_escape

    cases = [
        "",
        "plain",
        '"',
        "\\",
        "\n",
        "\r",
        "\t",
        "\x00leading-nul",
        'mix of "quotes" and \\backslashes\nplus\nnewlines',
        # 64-char hex stand-in for a HERMES_API_SERVER_KEY; intentionally
        # NOT in any provider's prefix format so secret-scanning ignores it.
        "deadbeef" * 8,
    ]
    for case in cases:
        assert module.toq(case) == _toml_escape(case), (
            f"toq filter drifted from _toml_escape for {case!r}: "
            f"plugin={module.toq(case)!r} python={_toml_escape(case)!r}"
        )


def test_filter_plugin_exposes_FilterModule_for_ansible():
    """Ansible discovers filter plugins by looking up `FilterModule()`
    with a `.filters()` method that returns a name→callable dict.
    Without this shape Ansible silently ignores the file."""
    import importlib.util

    repo_root = Path(__file__).resolve().parents[2]
    plugin_path = (
        repo_root
        / "src"
        / "clawrium"
        / "platform"
        / "registry"
        / "zeroclaw"
        / "playbooks"
        / "filter_plugins"
        / "clawrium_filters.py"
    )
    spec = importlib.util.spec_from_file_location(
        "_test_clawrium_filters_b", plugin_path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert hasattr(module, "FilterModule")
    filters = module.FilterModule().filters()
    assert "toq" in filters
    assert callable(filters["toq"])
