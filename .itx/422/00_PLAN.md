# Issue #422: Operators can drive zeroclaw onboarding for Discord and GitHub the same way as hermes

URL: https://github.com/ric03uec/clawrium/issues/422

<details>
<summary>Prompt Log</summary>

**Stage**: issue-creation
**Skill**: /itx:issue-new
**Timestamp**: 2026-05-18
**Model**: claude-opus-4-7

```prompt
then add support for both discord and github integration for zeroclaw first
the same way its there for hermes. follow official documentation of zeroclaw.
i will test it

[follow-up: "is aid read the documentation and find the right location. this
is not a opinon, you have to follow standards. add a task to udpate website
and documentation as well. update plan after doing your research"]
```

### Clarifications captured

- **Process**: Full `/itx:*` workflow — issue first, then plan-create, plan-scaffold, execute.
- **`[autonomy]` block**: Full upstream-default block + token names (not partial table) — avoids relying on undocumented daemon merge behavior.
- **Outcome statement**: "Operators can drive zeroclaw onboarding for Discord and GitHub the same way as hermes" (selected over agent-perspective and parity-emphasis alternatives).
- **Out of scope for this issue**: Slack on zeroclaw, GitHub MCP server, auto-installing `gh`, multi-agent Discord per host.

### Upstream-doc citations driving the design (zeroclaw v0.7.5)

- `docs/book/src/channels/chat-others.md` — Discord TOML schema (keys: `enabled`, `bot_token`, `allowed_guilds`, `allowed_users`, `reply_to_mentions_only`, `draft_update_interval_ms`).
- `docs/book/src/security/sandboxing.md` — `[autonomy] shell_env_passthrough` allowlist is the only documented path for exposing env vars to shell tools.
- `docs/book/src/security/autonomy.md` — full `[autonomy]` block schema; explicit rule that `_TOKEN`/`_SECRET`/`_PASSWORD`/`API_KEY` patterns are auto-blocked.
- `docs/book/src/ops/service.md` — systemd `Environment=` directive is the only documented daemon-env mechanism (no `EnvironmentFile=`).
- Full `docs/book/src/SUMMARY.md` + tree listing — no native `[integrations]` block in zeroclaw v0.7.5.

</details>
