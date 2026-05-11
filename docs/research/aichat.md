# aichat investigation — why we built our own REPL

Investigation note for issue #322 (generalize `clm chat` for hermes via OpenAI-compatible HTTP).

## What aichat is

[aichat](https://github.com/sigoden/aichat) is a Rust CLI for chatting with any OpenAI-compatible HTTP endpoint. It ships base-url configuration, multi-turn conversation history, model selection, slash-commands, session persistence, RAG, and a TUI. It's mature, well-maintained, and covers ~100% of the chat-client surface we'd ever need.

The question was whether to use it instead of writing our own client inside `clm`.

## Three options considered

### 1. aichat as a Rust library

**Verdict**: impractical.

aichat is published as a binary, not as a stable library API. There's no `crates.io` package surface intended for embedding. We'd have to vendor a Rust crate inside a Python project — `clm` is Python + Typer, `pyo3` bindings or a Rust submodule would dwarf the rest of the codebase, and we'd own all the maintenance.

### 2. aichat as a sidecar binary (clm shells out)

**Pros**:

- Zero TUI work — aichat already has a polished REPL.
- Multi-provider, multi-model, slash-commands, session history all free.

**Cons**:

- Extra runtime dependency. Every host running `clm chat` needs the aichat binary installed and on `$PATH`.
- Cross-platform Rust binary distribution. We'd have to bundle, fetch, or instruct users to install — none of which fits the `uv tool install clawrium` story.
- UX inconsistency. The rest of `clm` is Typer + Rich; shelling into aichat means a different prompt style, different keybinds, different config surface, different error formatting.
- Config drift. aichat has its own config file (`~/.config/aichat/config.yaml`); we'd either generate it from `hosts.json` (extra moving part) or ask users to maintain both.
- Updates are out of band. aichat releases land on its own cadence; a breaking change to its config schema becomes our incident.

### 3. Pure Python reference implementation (chosen for v1)

**Pros**:

- Consistent UX with `clm chat <openclaw-name>` and the rest of the CLI. Same Rich rendering, same Ctrl-C behavior, same exit-code conventions.
- No new system dependency — `httpx` is already in our dep tree after Slice 1.
- Errors map cleanly to `clm`'s remediation hints (`HERMES_API_SERVER_KEY` missing → "Re-run install"; `ConnectError` → "Check `systemctl --user status hermes`").
- Backend abstraction (`ChatBackend` protocol) reused for openclaw — one chat command, two transports.

**Cons**:

- More code to own. SSE parsing, history accumulation, model selection, and error mapping are all hand-rolled.
- We will reinvent features aichat already has (slash-commands, persistent sessions) if users ask for them.

## Why reference-implementation for v1

Three reasons:

1. **The minimum viable chat against hermes is small** — a couple hundred lines of `httpx` + SSE parsing — once you accept "no TUI bells, just openclaw parity." aichat solves a much larger problem than we have.
2. **Distribution simplicity wins**. `uv tool install clawrium` already gives users a working `clm chat`. Adding "and also install aichat" is a real onboarding regression.
3. **The abstraction we need anyway**. Slice 1 introduces a `ChatBackend` protocol so openclaw (websocket) and hermes (OpenAI HTTP) share the same CLI surface. Once that protocol exists, a Python `HermesOpenAIBackend` is the natural fit; an aichat-shelling-out backend is a second special case.

### What would tip us toward sidecar later

We'd reconsider aichat (or another existing client) as a sidecar if:

- **Users ask for a richer TUI** — pane-based history, search, image attachments, full markdown rendering of agent output.
- **Slash-commands and session persistence become load-bearing**. Right now `/reset` is the only slash-command and history is in-memory per REPL. If users want `/save`, `/load`, named conversations, branching, the maintenance burden flips.
- **Multi-provider support outside our agents** — i.e., `clm chat` against arbitrary OpenAI-compatible endpoints that aren't `clm`-managed agents. Today the value of `clm chat` is that it knows which agent on which host with which bearer; the moment that constraint relaxes, aichat's generality wins.

None of these are on the v1 roadmap. Revisit if a real user asks.

## Patterns worth stealing from aichat

Things aichat does well that the Python implementation should mirror:

- **Base-url config as a per-target field**. aichat lets you point `client.api_base` at any OpenAI-compatible URL with a bearer token. Our `_build_hermes_base_url(api_server, host_record)` mirrors this — `http://{host_record.hostname}:{port}/v1` — keeping the bind/reach split clean (`api_server.host` is the bind address, not the URL).
- **Conversation history as a plain list of `{role, content}` dicts**, appended client-side per turn, included verbatim in the next request. Don't try to be clever — the server is stateless, the client owns history. `/reset` is just `messages.clear()`.
- **Model selection as a config field, not a flag**. aichat reads the model from its per-client config; we read it from the agent manifest (`features.chat.model`) with no CLI override in v1. Add `--model` only if users actually want to switch.
- **Error mapping by status code**:
  - `401` → bearer wrong → "Re-run install to regenerate `HERMES_API_SERVER_KEY`."
  - `429` → rate limit → surface the upstream `Retry-After` header verbatim; don't auto-retry in the REPL.
  - `503` / `ConnectError` → service unreachable → "Check `systemctl --user status hermes` on `<host>`."
  - `5xx` other → print the body; let the user file an issue.
- **SSE handling**: aichat tolerates `data: [DONE]` sentinels, `:keep-alive` comment frames, and partial JSON across chunks. Our handwritten parser needs the same tolerance — covered by `test_sse_edge_cases`.

## Refs

- Parent: [#322](https://github.com/ric03uec/clawrium/issues/322)
- This issue: [#334](https://github.com/ric03uec/clawrium/issues/334)
- aichat: <https://github.com/sigoden/aichat>
