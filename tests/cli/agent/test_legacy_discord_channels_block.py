"""PR #747 W1 (ATX review): cover the legacy `clawctl` discord-wizard
channel-block shape so a future revert to `{"allow": True}` is caught
by `make test`, not by a human running `clawctl agent configure`.

The wizard logic lives in `clawrium.cli.agent._run_channels_stage` and
is partly-dead (per the clawctl-vs-legacy split) but still imported by
the test suite and reachable via the legacy `clawctl` entrypoint. The data
construction was extracted into `_build_legacy_discord_channels_block`
specifically so this invariant can be exercised in isolation.
"""

from __future__ import annotations

from clawrium.cli.agent import _build_legacy_discord_channels_block


def test_legacy_discord_block_channel_entry_is_empty_object():
    """Every `guilds.<id>.channels.<id>` entry MUST be `{}` (no `allow`).
    openclaw 2026.5.28+ rejects `allow` as an additional property; the
    canonical renderer emits the same shape — keep both paths aligned.
    """
    block = _build_legacy_discord_channels_block(
        guild_id="111111111111111111",
        channel_id="222222222222222222",
        user_id="333333333333333333",
    )

    chan_entry = block["guilds"]["111111111111111111"]["channels"][
        "222222222222222222"
    ]
    assert chan_entry == {}
    assert "allow" not in chan_entry


def test_legacy_discord_block_group_policy_pinned_allowlist():
    """`groupPolicy: "allowlist"` is required so the channel-presence
    invariant does not depend on openclaw's implicit default.
    """
    block = _build_legacy_discord_channels_block(
        guild_id="111111111111111111",
        channel_id="222222222222222222",
        user_id="333333333333333333",
    )
    assert block["groupPolicy"] == "allowlist"


def test_legacy_discord_block_full_structure():
    """Pin the full emitted shape so changes are caught at the test
    boundary, not at the on-host validator boundary.
    """
    block = _build_legacy_discord_channels_block(
        guild_id="111111111111111111",
        channel_id="222222222222222222",
        user_id="333333333333333333",
    )
    assert block == {
        "enabled": True,
        "token": {
            "source": "env",
            "provider": "default",
            "id": "DISCORD_BOT_TOKEN",
        },
        "allowFrom": ["333333333333333333"],
        "groupPolicy": "allowlist",
        "guilds": {
            "111111111111111111": {
                "users": ["333333333333333333"],
                "channels": {"222222222222222222": {}},
            }
        },
    }
