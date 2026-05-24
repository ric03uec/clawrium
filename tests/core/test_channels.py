"""Tests for the new `clawrium.core.channels` module (#509)."""

from __future__ import annotations

import json

import pytest

from clawrium.core import channels as ch


def test_add_get_round_trip(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    (tmp_path / "clawrium").mkdir()

    record = {
        "name": "my-disc",
        "type": "discord",
        "config": {
            "allowed_users": ["1"],
            "allowed_channels": ["2"],
            "require_mention": True,
        },
    }
    ch.add_channel(record)
    persisted = ch.get_channel("my-disc")
    assert persisted is not None
    assert persisted["type"] == "discord"
    assert persisted["config"]["allowed_users"] == ["1"]


def test_duplicate_add_raises(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    (tmp_path / "clawrium").mkdir()
    ch.add_channel({"name": "dup", "type": "discord", "config": {}})
    with pytest.raises(ch.DuplicateChannelError):
        ch.add_channel({"name": "dup", "type": "discord", "config": {}})


def test_invalid_type_rejected(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    (tmp_path / "clawrium").mkdir()
    with pytest.raises(ch.InvalidChannelTypeError):
        ch.validate_channel_type("irc")


def test_invalid_name_rejected(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    (tmp_path / "clawrium").mkdir()
    with pytest.raises(ch.InvalidChannelNameError):
        ch.validate_channel_name("1starts-with-digit")
    with pytest.raises(ch.InvalidChannelNameError):
        ch.validate_channel_name("has spaces")
    with pytest.raises(ch.InvalidChannelNameError):
        ch.validate_channel_name("")


def test_invalid_stream_mode_rejected(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    (tmp_path / "clawrium").mkdir()
    with pytest.raises(ch.InvalidStreamModeError):
        ch.validate_stream_mode("merge")
    # None is accepted (no-op).
    ch.validate_stream_mode(None)


def test_update_channel_writes_changes(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    (tmp_path / "clawrium").mkdir()
    ch.add_channel({"name": "u", "type": "slack", "config": {}})

    def updater(c: dict) -> dict:
        c.setdefault("config", {})["home_channel"] = "C42"
        return c

    assert ch.update_channel("u", updater) is True
    assert ch.get_channel("u")["config"]["home_channel"] == "C42"


def test_remove_channel_clears_record_and_credentials(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    (tmp_path / "clawrium").mkdir()
    ch.add_channel({"name": "rm", "type": "discord", "config": {}})
    ch.set_channel_token("rm", "BOT_TOKEN", "secret-bot")
    assert ch.get_channel_token("rm") == "secret-bot"

    assert ch.remove_channel("rm") is True
    assert ch.get_channel("rm") is None
    assert ch.get_channel_token("rm") is None


def test_remove_in_use_raises_unless_force(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    (tmp_path / "clawrium").mkdir()
    # Seed a hosts.json with an attached channel ref.
    (tmp_path / "clawrium" / "hosts.json").write_text(
        json.dumps(
            [
                {
                    "hostname": "h1",
                    "agents": {
                        "openclaw": {
                            "type": "openclaw",
                            "agent_name": "a1",
                            "channels": ["inuse"],
                        }
                    },
                }
            ]
        )
    )
    ch.add_channel({"name": "inuse", "type": "discord", "config": {}})

    with pytest.raises(ch.ChannelInUseError):
        ch.remove_channel("inuse")

    assert ch.remove_channel("inuse", force=True) is True


def test_set_channel_token_persists_and_round_trips(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    (tmp_path / "clawrium").mkdir()
    ch.set_channel_token("nm", "BOT_TOKEN", "abc")
    assert ch.get_channel_token("nm") == "abc"
    ch.set_channel_token("nm", "APP_TOKEN", "xapp")
    assert ch.get_channel_token("nm", "APP_TOKEN") == "xapp"


def test_agent_channel_attach_detach(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    (tmp_path / "clawrium").mkdir()
    (tmp_path / "clawrium" / "hosts.json").write_text(
        json.dumps(
            [
                {
                    "hostname": "h1",
                    "agents": {
                        "openclaw": {
                            "type": "openclaw",
                            "agent_name": "a1",
                        }
                    },
                }
            ]
        )
    )
    ch.add_channel({"name": "ac", "type": "discord", "config": {}})

    assert ch.add_agent_channel("h1", "openclaw", "ac") is True
    # Re-adding is a no-op.
    assert ch.add_agent_channel("h1", "openclaw", "ac") is False
    assert ch.get_agent_channels("h1", "openclaw") == ["ac"]

    assert ch.remove_agent_channel("h1", "openclaw", "ac") is True
    assert ch.remove_agent_channel("h1", "openclaw", "ac") is False


def test_channels_file_corrupted_raises(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    (tmp_path / "clawrium").mkdir()
    (tmp_path / "clawrium" / "channels.json").write_text("not json")
    with pytest.raises(ch.ChannelsFileCorruptedError):
        ch.load_channels()


def test_channels_file_wrong_shape_raises(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    (tmp_path / "clawrium").mkdir()
    (tmp_path / "clawrium" / "channels.json").write_text('{"not": "a list"}')
    with pytest.raises(ch.ChannelsFileCorruptedError):
        ch.load_channels()


def test_set_agent_channels_returns_false_on_unknown_agent(
    tmp_path, monkeypatch
) -> None:
    """ATX iter-2 W8: set_agent_channels must not report success when
    the agent_key is not present in the host's agents map."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    (tmp_path / "clawrium").mkdir()
    (tmp_path / "clawrium" / "hosts.json").write_text(
        json.dumps(
            [
                {
                    "hostname": "h1",
                    "agents": {
                        "openclaw": {
                            "type": "openclaw",
                            "agent_name": "a1",
                        }
                    },
                }
            ]
        )
    )
    assert ch.set_agent_channels("h1", "ghost-agent", ["c1"]) is False


def test_set_agent_channels_returns_true_on_known_agent(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    (tmp_path / "clawrium").mkdir()
    (tmp_path / "clawrium" / "hosts.json").write_text(
        json.dumps(
            [
                {
                    "hostname": "h1",
                    "agents": {
                        "a1": {
                            "type": "openclaw",
                            "agent_name": "a1",
                        }
                    },
                }
            ]
        )
    )
    assert ch.set_agent_channels("h1", "a1", ["c1"]) is True


def test_set_agent_channels_missing_host_returns_false(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    (tmp_path / "clawrium").mkdir()
    assert ch.set_agent_channels("no-such-host", "agent", ["c"]) is False


def test_update_channel_on_missing_record_returns_false(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    (tmp_path / "clawrium").mkdir()
    assert ch.update_channel("never-existed", lambda c: c) is False


def test_id_forbidden_rejects_bidi_codepoints() -> None:
    """ATX iter-2 W4: bidi-override codepoints must be rejected.

    Prior incidents (#341 v3 / #455 W2) — leaving these in stored IDs
    lets an attacker reverse-print the terminal when the value is
    later echoed.
    """
    # U+202E RIGHT-TO-LEFT OVERRIDE
    assert ch._ID_FORBIDDEN.search("abc‮def") is not None
    # U+200E LEFT-TO-RIGHT MARK
    assert ch._ID_FORBIDDEN.search("plain‎id") is not None
    # U+FEFF BOM
    assert ch._ID_FORBIDDEN.search("﻿id") is not None
    # U+2066 LEFT-TO-RIGHT ISOLATE
    assert ch._ID_FORBIDDEN.search("a⁦b") is not None
    # Plain ID stays clean.
    assert ch._ID_FORBIDDEN.search("1234567890") is None


def test_save_channels_is_not_exported() -> None:
    """ATX iter-2 W9: the public save helper was removed."""
    assert "save_channels" not in ch.__all__
    assert "_save_channels" not in ch.__all__
