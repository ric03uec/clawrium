# aichat investigation — why we built our own REPL

Investigation note for issue #322 (generalize `clawctl agent chat` for hermes via OpenAI-compatible HTTP).

> **Status (2026-05-11)**: This doc records the design decision behind Slices 1–4 of #322. It lands **before** those slices; symbols like `ChatBackend`, `HermesOpenAIBackend`, `_build_hermes_base_url`, `test_sse_edge_cases`, the `features.chat.type` enum, and the `httpx` dependency are the *target design* described in `.itx/322/00_PLAN.md`, not present code. Future tense is used where appropriate; assume nothing here exists in `src/` until the corresponding slice merges.

> **Context for newcomers**: Hermes is a self-hosted agent type that exposes an OpenAI-compatible HTTP gateway (`POST /v1/chat/completions`) secured by a bearer token. Contrast with openclaw, which exposes a WebSocket gateway. `clawctl agent chat` already works against openclaw; #322 generalizes it to hermes.

## What aichat is

[aichat](https://github.com/sigoden/aichat) is a Rust CLI for chatting with any OpenAI-compatible HTTP endpoint. It ships base-url configuration, multi-turn conversation history, model selection, slash-commands, session persistence, RAG, and a TUI. It's mature, well-maintained, and covers ~100% of the chat-client surface we'd ever need.

The question was whether to use it instead of writing our own client inside `clawctl`.

## Three options considered

### 1. aichat as a Rust library

**Verdict**: impractical.

aichat is published as a binary, not as a stable library API. There's no `crates.io` package surface intended for embedding. We'd have to vendor a Rust crate inside a Python project — `clawctl` is Python + Typer, `pyo3` bindings or a Rust submodule would dwarf the rest of the codebase, and we'd own all the maintenance.

### 2. aichat as a sidecar binary (clawctl shells out)

**Pros**:

- Zero TUI work — aichat already has a polished REPL.
- Multi-provider, multi-model, slash-commands, session history all free.

**Cons**:

- Extra runtime dependency. Every host running `clawctl agent chat` needs the aichat binary installed and on `$PATH`.
- Cross-platform Rust binary distribution. We'd have to bundle, fetch, or instruct users to install — none of which fits the `uv tool install clawrium` story. The binary cannot be hash-pinned in `pyproject.toml`.
- UX inconsistency. The rest of `clawctl` is Typer + Rich; shelling into aichat means a different prompt style, different keybinds, different config surface, different error formatting.
- Config drift. aichat has its own config file (`~/.config/aichat/config.yaml`); we'd either generate it from `hosts.json` (extra moving part) or ask users to maintain both.
- Updates are out of band. aichat releases land on its own cadence; a breaking change to its config schema becomes our incident, and we have no automatic enforcement against it.
- Secret exposure. The bearer would have to reach aichat somehow — as a CLI arg it appears in `ps aux` / `/proc/<pid>/cmdline`; as an env var it's still visible to same-uid processes via `/proc/<pid>/environ`. Neither matches the `0o600` `secrets.json` posture clawctl uses today.
- Subprocess lifecycle. "Zero TUI work" overstates the pro — an interactive REPL child needs PTY allocation (otherwise aichat disables readline/colour) and SIGINT forwarding (otherwise Ctrl-C in `clawctl` doesn't reach aichat cleanly).

### 3. Pure Python reference implementation (chosen for v1)

**Pros**:

- Consistent UX with `clawctl agent chat <openclaw-name>` and the rest of the CLI. Same Rich rendering, same Ctrl-C behavior, same exit-code conventions.
- No new system dependency. Slice 1 will add `httpx>=0.27` to `pyproject.toml` — small, well-maintained, BSD-licensed, FastAPI-ecosystem standard. No Rust toolchain, no binary distribution.
- Errors will map cleanly to `clawctl`'s remediation hints (`HERMES_API_SERVER_KEY` missing in `secrets.json` → "Re-run install"; `ConnectError` → "Check `systemctl status hermes-<agent-name>` on `<host>`").
- Backend abstraction (`ChatBackend` protocol introduced in Slice 1) reused for openclaw — one chat command, two transports.

**Cons**:

- More code to own. SSE parsing, history accumulation, model selection, and error mapping are all hand-rolled.
- We will reinvent features aichat already has (slash-commands, persistent sessions) if users ask for them.

## Why reference-implementation for v1

Three reasons:

1. **The minimum viable chat against hermes is small** — a couple hundred lines of `httpx` + SSE parsing — once you accept "no TUI bells, just openclaw parity." aichat solves a much larger problem than we have.
2. **Distribution simplicity wins**. `uv tool install clawrium` already gives users a working `clawctl agent chat`. Adding "and also install aichat" is a real onboarding regression.
3. **The abstraction we need anyway**. Slice 1 introduces a `ChatBackend` protocol so openclaw (websocket) and hermes (OpenAI HTTP) share the same CLI surface. Once that protocol exists, a Python `HermesOpenAIBackend` is the natural fit; an aichat-shelling-out backend is a second special case.

### What would tip us toward sidecar later

We'd reconsider aichat (or another existing client) as a sidecar if:

- **Users ask for a richer TUI** — pane-based history, search, image attachments, full markdown rendering of agent output.
- **Slash-commands and session persistence become load-bearing**. Right now `/reset` is the only slash-command and history is in-memory per REPL. If users want `/save`, `/load`, named conversations, branching, the maintenance burden flips.
- **Multi-provider support outside our agents** — i.e., `clawctl agent chat` against arbitrary OpenAI-compatible endpoints that aren't `clawctl`-managed agents. Today the value of `clawctl agent chat` is that it knows which agent on which host with which bearer; the moment that constraint relaxes, aichat's generality wins.
- **Injection safety is a hard constraint**: if we ever do shell out to aichat, user chat messages MUST be piped to its stdin — never interpolated into a shell command or CLI argument, and never with `shell=True`. PR #68 already had to fix a command-injection bug in `validate_hermes_health`; the next sidecar implementation cannot repeat it.

None of these are on the v1 roadmap. Revisit if a real user asks.

## Patterns worth stealing from aichat

Things aichat does well that the Python implementation should mirror (all of these are *target design* — not yet present in `src/`):

- **Base-url config as a per-target field**. aichat lets you point `client.api_base` at any OpenAI-compatible URL with a bearer token. The planned `_build_hermes_base_url(api_server, host_record)` will mirror this — `http://{host_record.hostname}:{port}/v1` — keeping the bind/reach split clean: `api_server.host` in `hosts.json` is the *bind* address (Slice 1 will flip it from `127.0.0.1` to `0.0.0.0` per `.itx/322/00_PLAN.md`), while `host_record.hostname` is the *reach* address used in the URL.
- **LAN transport is plaintext HTTP** — this is a deliberate trade, not an oversight. The threat model matches openclaw's existing `bind: "lan"`: bearer + Authorization header travel over LAN HTTP. Hermes' own startup check (`gateway/platforms/api_server.py:3150–3169`, the `is_network_accessible` guard) refuses to bind a non-loopback interface without a strong, non-placeholder key; our 64-char hex `secrets.token_hex(32)` (`core/install.py:547`) satisfies that. TLS / SSH-tunnel is out of scope for v1 and would be a follow-up if homelab threat models tighten. (Slice 1 will also need to update `docs/agent-support/hermes.md:191` which currently states non-loopback is unsupported.)
- **Conversation history as a plain list of `{role, content}` dicts**, appended client-side per turn, included verbatim in the next request. Don't try to be clever — the server is stateless, the client owns history. `/reset` will just `messages.clear()`.
- **Model selection as a config field, not a flag**. aichat reads the model from its per-client config; clawctl will source the model from `config.provider.default_model` in the agent's persisted `hosts.json` entry, which `templates/config.yaml.j2` will render as `model.default` in `~/.hermes/config.yaml` during `clawctl agent configure` (template reads the value at line 8: `{% set model_id = provider.default_model | default('') %}`, and writes it at lines 33–34 under the top-level `model:` block). Separately, `features.chat.type` in the manifest (added by Slice 1) is purely a dispatch *discriminator* — `"websocket"` for openclaw, `"openai"` for hermes — not for model selection. No `--model` CLI override in v1.
- **Credential surface**: aichat stores credentials in `~/.config/aichat/config.yaml` which is world-readable by default. clawctl will read the bearer from `~/.config/clawrium/secrets.json` (`0o600`) via `get_instance_secrets()` — never from a config file, never via an env var that could leak to `0644`.
- **Error mapping by status code**:
  - `401` → bearer wrong → "Re-run install to regenerate the hermes bearer (`HERMES_API_SERVER_KEY` in `clawctl`'s `secrets.json` per `core/install.py:535,550`; rendered into the agent's `.env` as `API_SERVER_KEY` by `templates/.env.j2:29`)."
  - `429` → rate limit → surface the upstream `Retry-After` header verbatim; don't auto-retry in the REPL.
  - `503` / `ConnectError` → service unreachable → "Check `systemctl status hermes-<agent-name>.service` on `<host>`." (Hermes installs as a system unit at `/etc/systemd/system/hermes-<agent-name>.service`, not a user unit — no `--user` flag.)
  - `5xx` other → print the body; let the user file an issue.
  - **All httpx exception strings** must pass through a sanitizer before display — raw httpx exceptions can include full URLs and request headers, which means the bearer can leak into terminal scrollback. Openclaw's `_sanitize_exception_text` (`cli/chat.py:309–317`) is the right starting model, **but it has a known gap**: the current regex `\b(token|auth|password)\b\s*[:=]\s*` does not match `"Authorization: Bearer <token>"` — `\bauth\b` fails before the `o` in `Authorization`, and there is no `:`/`=` between `Bearer` and the token. Slice 3 must extend the sanitizer with an explicit `(?i)\bBearer\s+([A-Za-z0-9._~+/-]{1,})` → `Bearer ***` substitution before reusing the function for hermes, or the gap propagates. (Use `{1,}` — not `{8,}` — so the regex doesn't silently let short test/dev tokens through.)
- **SSE handling**: aichat tolerates `data: [DONE]` sentinels, `:keep-alive` comment frames, and partial JSON across chunks. The planned handwritten parser will need the same tolerance — to be covered by `tests/test_chat_hermes.py::test_sse_edge_cases` in Slice 3.

## Refs

- Parent: [#322](https://github.com/ric03uec/clawrium/issues/322)
- This issue: [#334](https://github.com/ric03uec/clawrium/issues/334)
- aichat: <https://github.com/sigoden/aichat>
