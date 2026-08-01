Apply the following four small edits and then run `make lint && make test`. Do NOT read the GitHub issue body — everything you need is here. Do NOT create any new files. Do NOT touch anything under `src/clawrium/core/` or the Jinja templates. Do NOT add an interactive prompt. Scope is CLI unblock + help text + tests only.

## Edit 1 — `src/clawrium/cli/clawctl/channel.py` (create subcommand, around line 274)

Find this block:

```python
if app_token and channel_type != "slack":
    emit_error(f"--app-token only valid for slack channels (got {channel_type!r})")
if home_channel and channel_type != "slack":
    emit_error(
        f"--home-channel only valid for slack channels (got {channel_type!r})"
    )
```

Delete the `--home-channel` guard entirely (the whole `if home_channel and channel_type != "slack": ...` block, keeping only the `--app-token` guard above it).

Also update the `--home-channel` typer.Option help string in the create subcommand (around line 232-234):

```python
home_channel: Optional[str] = typer.Option(
    None, "--home-channel", help="Default channel ID (Slack)."
),
```

Change the help to: `"Default channel ID (Slack or Discord)."`

## Edit 2 — `src/clawrium/cli/clawctl/channel.py` (edit subcommand, around line 531)

Find and delete this line:

```python
if home_channel and ctype != "slack":
    emit_error(f"--home-channel only valid for slack channels (got {ctype!r})")
```

Also update the `--home-channel` help in the edit subcommand (around line 485-487):

```python
home_channel: Optional[str] = typer.Option(
    None, "--home-channel", help="New default channel (Slack)."
),
```

Change to: `"New default channel (Slack or Discord)."`

## Edit 3 — `tests/cli/clawctl/channel/test_registry.py`

Append four tests at the bottom of the file, mirroring the shape of `test_create_app_token_rejected_on_discord` and `test_create_slack_with_stream_mode`:

```python
def test_create_discord_with_home_channel(fleet_dir, stdin_not_tty) -> None:
    """--home-channel is now accepted for discord channels (was previously blocked)."""
    result = runner.invoke(
        app,
        [
            "channel",
            "registry",
            "create",
            "myd",
            "--type",
            "discord",
            "--token",
            "d-tok-123",
            "--home-channel",
            "1234567890",
        ],
    )
    assert result.exit_code == 0, result.output
    describe = runner.invoke(app, ["channel", "registry", "describe", "myd"])
    assert "Home channel:" in describe.output
    assert "1234567890" in describe.output


def test_edit_discord_home_channel(fleet_dir, stdin_not_tty) -> None:
    """--home-channel edit works for discord channels."""
    runner.invoke(
        app,
        [
            "channel",
            "registry",
            "create",
            "myd2",
            "--type",
            "discord",
            "--token",
            "d-tok-456",
        ],
    )
    result = runner.invoke(
        app, ["channel", "registry", "edit", "myd2", "--home-channel", "9999"]
    )
    assert result.exit_code == 0, result.output
    describe = runner.invoke(app, ["channel", "registry", "describe", "myd2"])
    assert "9999" in describe.output


def test_create_home_channel_still_works_for_slack(fleet_dir, stdin_not_tty) -> None:
    """Regression guard: --home-channel still works for slack (unchanged behavior)."""
    result = runner.invoke(
        app,
        [
            "channel",
            "registry",
            "create",
            "mysl",
            "--type",
            "slack",
            "--token",
            "s-tok",
            "--app-token",
            "s-app",
            "--home-channel",
            "C123",
        ],
    )
    assert result.exit_code == 0, result.output


def test_edit_home_channel_still_works_for_slack(fleet_dir, stdin_not_tty) -> None:
    """Regression guard: --home-channel edit still works for slack."""
    runner.invoke(
        app,
        [
            "channel",
            "registry",
            "create",
            "mysl2",
            "--type",
            "slack",
            "--token",
            "s-tok",
            "--app-token",
            "s-app",
        ],
    )
    result = runner.invoke(
        app, ["channel", "registry", "edit", "mysl2", "--home-channel", "C456"]
    )
    assert result.exit_code == 0, result.output
```

## Edit 4 — `CHANGELOG.md`

Under `## [Unreleased]` → `### Changed` (create the subsection if it does not exist), add exactly one bullet:

```
- `clawctl channel registry create/edit --home-channel <id>` now accepts Discord channels in addition to Slack; the Jinja `hermes-env.canonical.j2` template already emitted `DISCORD_HOME_CHANNEL` when the field was set, only the CLI guards blocked it (#642).
```

## After the four edits

1. `make lint` — must pass.
2. `make test` — must pass. All 4 new tests must pass; existing tests must not regress.
3. `git add -A` (only the files you edited plus `.itx/642/`)
4. `git commit -m "feat(#642): allow --home-channel on Discord channels"` — with a short body describing the guard removal + template pre-existing support.
5. `echo done > .itx/642/lmwork-worker.done`

## Absolute prohibitions

- Do NOT edit `src/clawrium/platform/registry/hermes/templates/hermes-env.canonical.j2` (already correct).
- Do NOT edit `src/clawrium/core/channels.py` or `src/clawrium/core/render.py`.
- Do NOT add an interactive prompt for `--home-channel` in `channel registry create`. That is a follow-up.
- Do NOT touch `hosts/`, `.hermes/`, or any playbook.
- Do NOT run `git push`. Do NOT open a PR.
- Do NOT create new label / issue.

Start immediately. Do not spawn an Explore subagent — every file is named above with its edit location.
