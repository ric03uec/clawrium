# Brave Search

**Status:** ✅ Supported on Hermes, ZeroClaw, and OpenClaw (#734).

Brave Search integration gives agents a real web-search tool. The credential
is a Brave Search API subscription token (free tier available at
https://brave.com/search/api/). Operators store the key once in the
clawrium registry and attach the integration to any supported agent —
clawrium handles the per-agent env var shape (including the upstream
name mapping on hermes and the search-provider router override on
zeroclaw) so the operator never sees those details.

---

## Per-Agent Env Shape

The credential the operator passes is always `BRAVE_API_KEY`. Each
agent's renderer maps it to the env var(s) the upstream daemon
actually reads:

| Agent | Env vars written | Notes |
|---|---|---|
| **hermes** | `BRAVE_SEARCH_API_KEY=<key>` | Name-mapped in the template. Hermes' `web_search` tool reads `BRAVE_SEARCH_API_KEY`, **not** `BRAVE_API_KEY` (see upstream PR `nousresearch/hermes-agent#21337`). |
| **zeroclaw** | `BRAVE_API_KEY=<key>` **and** `ZEROCLAW_web_search__search_provider=brave` | Both lines are required. Setting the key alone leaves the provider router on its `duckduckgo` default. The companion env-prefix override (`web_search_provider_routing.rs:33`) flips the router to brave. |
| **openclaw** | `BRAVE_API_KEY=<key>` | Openclaw's brave plugin reads the env var directly (plugin manifest declares it as the first-class fallback for `webSearch.apiKey`). Plugin install happens automatically on `clawctl agent configure` (see below). |

The same registry entry can be attached to multiple agents of different
types — each agent's renderer produces the correct shape independently.

---

## Openclaw plugin install + min-version preflight

Openclaw needs the `@openclaw/brave-plugin` npm package installed
locally on the agent host. `clawctl agent configure` and
`clawctl agent sync` handle that automatically when a brave
integration is attached — installation is idempotent and gated by a
per-version sentinel file at
`~/.openclaw/.brave-plugin-installed.<version>`.

Pinned version: **`@openclaw/brave-plugin@2026.6.8`**. The pin lives in
`src/clawrium/platform/registry/openclaw/manifest.yaml`
(`plugins.brave.version`) so a bump is a single-line change.

The plugin declares `minHostVersion >= 2026.4.10`. `clawctl agent sync`
preflights the on-host openclaw version over SSH before any write —
if the host is older the sync exits with a clear message:

```
openclaw on <host> is <ver>; brave plugin requires >= 2026.4.10.
Run `clawctl agent upgrade <agent>` first.
```

This is intentional friction. Silently working with a missing plugin
would surface as an opaque daemon-side error much later.

---

## Get a Brave Search API key

1. Sign up at https://brave.com/search/api/ (free tier available).
2. From the dashboard, create a new subscription token.
3. Copy the value — Brave does not show it twice.

---

## Use with Clawrium

### Register the integration

```bash
# Convenience flag for single-credential types — value never lands in
# `ps`/shell history via a positional argument.
clawctl integration registry create my-brave --type brave --api-key bsk-xxxxx

# Or, for CI / secret-manager pipelines:
printf %s "$BRAVE_API_KEY" | clawctl integration registry create my-brave \
  --type brave --api-key-stdin
```

### Attach to an agent

```bash
clawctl agent integration attach <agent-name> my-brave
clawctl agent sync <agent-name>
```

### Rotate the key

When the upstream key changes:

```bash
clawctl integration rotate my-brave --api-key bsk-new-xxxxx --yes
```

This updates the credential **and** re-syncs every agent currently
bound to `my-brave` in one shot. Any sync failure surfaces as
non-zero exit so cron-driven rotations don't silently leave
half-rotated state.

### Delete

```bash
clawctl integration registry delete my-brave
```

Refuses if any agent is still attached unless `--force` is passed
(which detaches + re-syncs all bound agents).
