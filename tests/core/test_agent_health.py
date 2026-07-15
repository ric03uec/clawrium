"""Tests for core.agent_health — structured doctor health checks.

All SSH and subprocess calls are mocked so the test suite runs without a
real remote host.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from clawrium.core.agent_health import (
    CheckResult,
    _check_onboarding,
    _check_token,
    _skipped_checks,
    run_doctor_checks,
)


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────


def _host_data(
    hostname: str = "192.168.1.10",
    port: int = 22,
    user: str = "xclm",
    key_id: str = "host-key-abc",
    gateway_port: int = 44100,
) -> dict:
    return {
        "hostname": hostname,
        "port": port,
        "user": user,
        "key_id": key_id,
        "agents": {
            "kevin": {
                "type": "ethos",
                "agent_name": "kevin",
                "config": {
                    "gateway": {"port": gateway_port},
                },
                "onboarding": {"state": "ready"},
            }
        },
    }


def _agent_record(
    gateway_port: int = 44100,
    onboarding_state: str = "ready",
) -> dict:
    return {
        "type": "ethos",
        "agent_name": "kevin",
        "config": {
            "gateway": {"port": gateway_port},
        },
        "onboarding": {"state": onboarding_state},
    }


# ──────────────────────────────────────────────────────────────────────────────
# CheckResult dataclass
# ──────────────────────────────────────────────────────────────────────────────


def test_check_result_defaults():
    r = CheckResult(name="SSH reachable", status="pass", detail="ok")
    assert r.hint is None


def test_check_result_with_hint():
    r = CheckResult(name="Unit running", status="fail", detail="inactive", hint="start it")
    assert r.hint == "start it"


# ──────────────────────────────────────────────────────────────────────────────
# _skipped_checks helper
# ──────────────────────────────────────────────────────────────────────────────


def test_skipped_checks_returns_correct_names():
    names = ["A", "B", "C"]
    results = _skipped_checks(names)
    assert len(results) == 3
    assert all(r.status == "skip" for r in results)
    assert [r.name for r in results] == names


# ──────────────────────────────────────────────────────────────────────────────
# _check_onboarding
# ──────────────────────────────────────────────────────────────────────────────


def test_check_onboarding_ready():
    record = {"onboarding": {"state": "ready"}}
    r = _check_onboarding(agent_record=record, agent_name="kevin")
    assert r.status == "pass"
    assert "ready" in r.detail


def test_check_onboarding_pending():
    record = {"onboarding": {"state": "pending"}}
    r = _check_onboarding(agent_record=record, agent_name="kevin")
    assert r.status == "fail"
    assert "pending" in r.detail
    assert r.hint is not None


def test_check_onboarding_in_progress():
    record = {"onboarding": {"state": "providers"}}
    r = _check_onboarding(agent_record=record, agent_name="kevin")
    assert r.status == "fail"
    assert "providers" in r.detail


def test_check_onboarding_missing_record():
    record = {}
    r = _check_onboarding(agent_record=record, agent_name="kevin")
    assert r.status == "fail"
    assert r.hint is not None


def test_check_onboarding_non_dict_record():
    record = {"onboarding": "invalid"}
    r = _check_onboarding(agent_record=record, agent_name="kevin")
    assert r.status == "fail"


# ──────────────────────────────────────────────────────────────────────────────
# _check_token
# ──────────────────────────────────────────────────────────────────────────────


@patch("clawrium.core.agent_health.get_instance_secrets")
@patch("clawrium.core.agent_health.get_instance_key")
def test_check_token_pass(mock_get_key, mock_get_secrets):
    mock_get_key.return_value = "host-key-abc:ethos:kevin"
    mock_get_secrets.return_value = {"ETHOS_API_KEY": {"key": "ETHOS_API_KEY", "value": "tok"}}

    r = _check_token(
        host_data=_host_data(),
        agent_type="ethos",
        agent_name="kevin",
    )
    assert r.status == "pass"
    assert "1 secret" in r.detail


@patch("clawrium.core.agent_health.get_instance_secrets")
@patch("clawrium.core.agent_health.get_instance_key")
def test_check_token_empty_secrets(mock_get_key, mock_get_secrets):
    mock_get_key.return_value = "host-key-abc:ethos:kevin"
    mock_get_secrets.return_value = {}

    r = _check_token(
        host_data=_host_data(),
        agent_type="ethos",
        agent_name="kevin",
    )
    assert r.status == "fail"
    assert r.hint is not None


@patch("clawrium.core.agent_health.get_instance_key")
def test_check_token_invalid_key_component(mock_get_key):
    from clawrium.core.secrets import InvalidInstanceKeyComponentError

    mock_get_key.side_effect = InvalidInstanceKeyComponentError("bad char")

    r = _check_token(
        host_data=_host_data(),
        agent_type="ethos",
        agent_name="kevin",
    )
    assert r.status == "fail"
    assert "invalid instance key" in r.detail


# ──────────────────────────────────────────────────────────────────────────────
# run_doctor_checks — full pipeline
# ──────────────────────────────────────────────────────────────────────────────


def _make_ssh_key_mock(exists: bool = True):
    """Return a mock Path-like object (or None) for get_host_private_key."""
    if not exists:
        return None
    m = MagicMock()
    m.__str__ = lambda self: "/fake/key/path"
    return m


@patch("clawrium.core.agent_health._check_onboarding")
@patch("clawrium.core.agent_health._check_token")
@patch("clawrium.core.agent_health._check_gateway")
@patch("clawrium.core.agent_health._check_unit")
@patch("clawrium.core.agent_health._check_ssh")
def test_all_checks_pass(
    mock_ssh, mock_unit, mock_gw, mock_token, mock_onboard
):
    mock_ssh.return_value = CheckResult("SSH reachable", "pass", "192.168.1.10:22")
    mock_unit.return_value = CheckResult("Unit running", "pass", "ethos-kevin.service — active")
    mock_gw.return_value = CheckResult("Gateway reachable", "pass", "port 44100 is listening")
    mock_token.return_value = CheckResult("Token stored", "pass", "1 secret(s) stored")
    mock_onboard.return_value = CheckResult("Onboarding complete", "pass", "state=ready")

    with patch("clawrium.core.agent_health.get_host_private_key", return_value=_make_ssh_key_mock()):
        results = run_doctor_checks(
            agent_name="kevin",
            host_data=_host_data(),
            agent_type="ethos",
            agent_record=_agent_record(),
        )

    assert len(results) == 5
    assert all(r.status == "pass" for r in results)


@patch("clawrium.core.agent_health._check_ssh")
def test_ssh_fail_skips_rest(mock_ssh):
    mock_ssh.return_value = CheckResult(
        "SSH reachable", "fail", "Network error", hint="check network"
    )

    results = run_doctor_checks(
        agent_name="kevin",
        host_data=_host_data(),
        agent_type="ethos",
        agent_record=_agent_record(),
    )

    assert len(results) == 5
    assert results[0].status == "fail"
    assert results[0].name == "SSH reachable"
    # All subsequent checks skipped
    assert all(r.status == "skip" for r in results[1:])


@patch("clawrium.core.agent_health._check_onboarding")
@patch("clawrium.core.agent_health._check_token")
@patch("clawrium.core.agent_health._check_gateway")
@patch("clawrium.core.agent_health._check_unit")
@patch("clawrium.core.agent_health._check_ssh")
def test_unit_fail_skips_gateway_onwards(
    mock_ssh, mock_unit, mock_gw, mock_token, mock_onboard
):
    mock_ssh.return_value = CheckResult("SSH reachable", "pass", "192.168.1.10:22")
    mock_unit.return_value = CheckResult(
        "Unit running", "fail", "ethos-kevin.service — inactive", hint="start it"
    )

    with patch("clawrium.core.agent_health.get_host_private_key", return_value=_make_ssh_key_mock()):
        results = run_doctor_checks(
            agent_name="kevin",
            host_data=_host_data(),
            agent_type="ethos",
            agent_record=_agent_record(),
        )

    assert results[0].status == "pass"  # SSH
    assert results[1].status == "fail"  # unit
    assert all(r.status == "skip" for r in results[2:])
    # Gateway, token, onboarding mocks should not have been called
    mock_gw.assert_not_called()
    mock_token.assert_not_called()
    mock_onboard.assert_not_called()


@patch("clawrium.core.agent_health._check_onboarding")
@patch("clawrium.core.agent_health._check_token")
@patch("clawrium.core.agent_health._check_gateway")
@patch("clawrium.core.agent_health._check_unit")
@patch("clawrium.core.agent_health._check_ssh")
def test_gateway_fail_skips_token_and_onboarding(
    mock_ssh, mock_unit, mock_gw, mock_token, mock_onboard
):
    mock_ssh.return_value = CheckResult("SSH reachable", "pass", "ok")
    mock_unit.return_value = CheckResult("Unit running", "pass", "active")
    mock_gw.return_value = CheckResult(
        "Gateway reachable", "fail", "connection refused on port 44100", hint="start agent"
    )

    with patch("clawrium.core.agent_health.get_host_private_key", return_value=_make_ssh_key_mock()):
        results = run_doctor_checks(
            agent_name="kevin",
            host_data=_host_data(),
            agent_type="ethos",
            agent_record=_agent_record(),
        )

    assert results[0].status == "pass"  # SSH
    assert results[1].status == "pass"  # unit
    assert results[2].status == "fail"  # gateway
    assert results[3].status == "skip"  # token
    assert results[4].status == "skip"  # onboarding
    mock_token.assert_not_called()
    mock_onboard.assert_not_called()


@patch("clawrium.core.agent_health._check_ssh")
def test_missing_ssh_key_fails_first_check(mock_ssh):
    """When get_host_private_key returns None, check 1 must fail."""
    mock_ssh.return_value = CheckResult(
        "SSH reachable", "fail", "no SSH key found for host key_id='host-key-abc'"
    )

    results = run_doctor_checks(
        agent_name="kevin",
        host_data=_host_data(),
        agent_type="ethos",
        agent_record=_agent_record(),
    )

    assert results[0].status == "fail"
    assert all(r.status == "skip" for r in results[1:])


def test_result_count_always_five():
    """run_doctor_checks always returns exactly 5 results regardless of failure point."""
    with patch("clawrium.core.agent_health._check_ssh") as mock_ssh:
        mock_ssh.return_value = CheckResult("SSH reachable", "fail", "unreachable")
        results = run_doctor_checks(
            agent_name="kevin",
            host_data=_host_data(),
            agent_type="ethos",
            agent_record=_agent_record(),
        )
    assert len(results) == 5
