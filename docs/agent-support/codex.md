# Codex Support

Clawrium supports `codex` as an **isolated, per-agent Codex CLI environment**. It is daemonless: installation prepares a dedicated account, and exec or chat starts a bounded native Codex process only when requested.

**Pinned version:** `0.160.1`

**Supported targets:** Ubuntu 22.04/24.04 x86_64 and macOS 14+ Apple Silicon.

## Install and authenticate

```bash
clawctl agent create <name> --type codex --host <host>
clawctl provider registry create local-codex-oauth --type codex-oauth
clawctl agent provider attach local-codex-oauth --agent <name>
clawctl agent sync <name>
```

Create installs the pinned `@openai/codex` package into the dedicated user's
owned `~/.local/codex` prefix. It does not start Codex, a service, gateway,
listener, tunnel, web UI, persistent chat process, or pairing flow.

`codex-oauth` is selection-only and can attach only to a Codex agent. Attach
imports only the supported controller-side native file-backed Codex login into
the selected agent's encrypted instance secrets. It does not read a keychain,
browser profile, or arbitrary directory. Missing, unsupported, malformed, or
unsafe local credentials fail with an actionable error; re-attaching explicitly
refreshes the selected snapshot without printing it.

Sync activates the document as private `~/.codex/auth.json` (`0600`) under the
dedicated account. Routine configure/sync preserves a valid remote document
because Codex may refresh it in place; an explicit re-attach replaces it.
Credentials never enter provider metadata, `hosts.json`, diff output, command
argv, events, or logs. If the remote document is missing or unusable, reattach
and sync rather than copying credentials manually.

## On-demand chat

```bash
clawctl agent chat <name>
clawctl agent chat <name> --once "Summarize the current workspace"
```

Each turn runs the pinned native protocol as the dedicated user:
`codex exec --json --skip-git-repo-check -` for a fresh conversation, then
`codex exec resume --json --skip-git-repo-check <thread-id> -` for later REPL
turns. The flag permits execution from the agent's isolated, non-Git home; it
does not alter credential selection. Prompts go on
stdin, never into a shell fragment or command argv. `/reset` and `--once`
start a fresh native thread. The finite process is timeout-bounded; malformed
JSONL, nonzero exits, and authentication failures produce safe chat errors
without relaying prompt text, credentials, remote stderr, or paths.

The **Chat** tab in `clawctl gui` uses this exact backend. Browser conversations
have independent native-thread state; **New chat** starts fresh. The GUI does
not transfer credentials to a browser and generic SSE errors expose no remote
diagnostic details.

## Exec, shell, and unavailable daemon operations

```bash
clawctl agent exec <name> -- --version
clawctl agent shell <name> -- 'codex --version'
```

`exec` uses the dedicated pinned binary with structured argv and a finite
runtime; `shell` is for terminating shell expressions. Both run with the
private `CODEX_HOME` in the agent home. `start`, `stop`, `restart`, `logs`,
`open`, native web UI, tunnel, port, and pairing are unavailable: Codex has no
Clawrium-managed daemon. Use `agent get` or `agent describe` for installed
state.

## Removal

```bash
clawctl agent delete --yes <name>
```

After remote cleanup succeeds, Clawrium removes that instance's dedicated
account, home, install prefix, private Codex state, ownership marker, local
instance secrets, and fleet record. It never removes a separately installed
system/global Codex distribution. If remote cleanup fails, local state remains
so the operation can be retried safely.

## Verification callout

Automated tests cover OAuth activation, refresh-safe sync, finite CLI/GUI chat,
JSONL parsing, continuation/reset, timeout, cancellation, and redaction. On
wolf-i (Ubuntu), a disposable Codex 0.160.1 agent passed install and native
exec/shell version checks. A controller file-backed ChatGPT login was attached
through a selection-only provider and synced to the agent's private `0600`
auth file; native `login status`, CLI chat, and GUI chat all succeeded. CLI and
GUI conversations continued across turns and reset to fresh threads. An
ordinary repeat sync left the remote auth file unchanged and inference still
worked. The earlier no-auth disposable agent was also removed successfully.

The repeat-sync check did not observe an actual remote token refresh. mac-test
was unreachable over SSH, so live macOS validation remains outstanding. Its
failed local `codex-1031-uat` install record remains for safe retry and remote
cleanup when that host is reachable; no remote install tasks ran during the
failed attempt. See `.itx/1031/01_EXECUTION.md` for the verification ledger.
