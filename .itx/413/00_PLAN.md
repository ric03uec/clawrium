# Issue #413: User can run agent-native commands on remote hosts without SSH using `clm agent pt`

URL: https://github.com/ric03uec/clawrium/issues/413

<details>
<summary>Prompt Log</summary>

**Stage**: issue-creation
**Skill**: /itx:issue-new
**Timestamp**: 2026-05-18
**Model**: claude-opus-4-7

```prompt
Create a new feature request. Add support for a CLI command, called CLM agent PT
options. PT stands for pass through. This is a way for users to send agent
specific commands to the agent without logging into the host machine. This is
there to support native commands on the agents without getting SSH access to
the host. Users might need to configure Hermes, Zeroclaw or Openclaw based on
the respective agent's CLI. This option is not supported right now, but the
passthrough option in CLM will allow users to do that.
```

### Clarifications captured

- **Syntax**: `clm agent pt <name> -- <cmd>` (Unix `--` separator convention)
- **Output**: Stream live (stdout/stderr) to local terminal
- **Interactivity**: Non-interactive only in v1 (no TTY)
- **Agent types in v1**: hermes, zeroclaw, openclaw (nemoclaw out of scope)
- **Exit code propagation**: Required (must propagate remote exit code as `clm` exit code)

</details>
