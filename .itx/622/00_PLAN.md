# Implementation Plan — #622 (v3, scope: kill legacy hermes templates)

`bug(template): hermes-config.canonical.yaml.j2 doesn't iterate config.providers — no auxiliary.<role> rendering on sync path`

## Scope (final, after user feedback)

Multi-provider attachments are a **hermes-only** feature. The legacy
ansible-templating path for hermes config files is the source of the bug
and is now duplicated dead weight. Kill it.

Concrete:

1. Delete `hermes-config.yaml.j2` and `hermes.env.j2` (the legacy `.j2`
   files that the ansible playbook templates server-side).
2. Rewrite `configure.yaml` and `configure_macos.yaml` so the playbook
   no longer renders those templates. The two `ansible.builtin.template:`
   tasks for those files (configure.yaml:107-131 and
   configure_macos.yaml:54-66) are replaced with `ansible.builtin.copy:`
   tasks that ship pre-rendered bytes prepared by `render_hermes` on the
   clawctl side.
3. Have `lifecycle.configure_agent` route hermes through `render_hermes`
   (the same function the canonical sync path uses) and pass the
   rendered bytes to ansible via a temp file or extravars-as-content.
   `render_hermes` is the single source of truth for the on-host
   `~/.hermes/config.yaml` and `~/.hermes/.env` shapes from now on.
4. Remove legacy `lifecycle.sync_agent` (lifecycle.py:1169) if no live
   caller remains after step 3. Verified callers today are
   `cli/agent.py:2640` (legacy `clm agent sync` — not shipped as a
   console script per `pyproject.toml`) and `cli/clawctl/agent/configure.py:27`
   (production `clawctl agent configure`). Step 3 rewires the production
   caller; the legacy `clm` caller goes when the function does.
5. Delete `cli/agent.py:cmd_sync` (and the legacy `clm agent sync`
   command surface) along with the legacy templates — it's a duplicate
   surface of the production `clawctl agent sync`, which already routes
   through `sync_agent_canonical` (the canonical path that consumes
   `render_hermes` correctly).
6. Prune `tests/test_hermes_configure.py` (3000+ lines) to drop the
   `hermes-config.yaml.j2` / `hermes.env.j2` template assertions. Keep
   the tests that exercise the surviving playbook tasks (gh auth,
   mcp_servers cmd verification, ~/.gitconfig render).
7. Remove the two hermes-template references from
   `src/clawrium/platform/registry/zeroclaw/templates/zeroclaw-env.conf.j2`
   (lines 21, 53 are comments pointing at `hermes/hermes.env.j2:115-122`
   and `hermes.env.j2:111-114`). Zeroclaw should not reference hermes.
   Replace each with a self-contained comment explaining the zeroclaw
   rule on its own terms.
8. CHANGELOG `### Changed` entry under `[Unreleased]` documenting that
   hermes `~/.hermes/config.yaml` and `~/.hermes/.env` are now rendered
   client-side by `render_hermes`. Not operator-breaking — see §3.
9. AGENTS.md hermes section gets a one-line note that `render_hermes`
   is the single rendering path; drop the legacy-template lockstep
   language proposed in earlier plan revisions (no lockstep needed when
   there's only one path).

Out of scope (explicitly):

- Zeroclaw, openclaw, nemoclaw multi-provider. **Not a feature for
  these agents.** Their renderers / templates are untouched.
- Any new operator-facing flag, command, or migration step.
- Renaming `.canonical.yaml.j2` → `.yaml.j2`. The canonical filename
  stays; the legacy one is just deleted. Renaming is churn.

---

## 1. Current state on `main` (verified)

| Operator command | Internal path | Templates | Multi-provider? |
|---|---|---|---|
| `clawctl agent sync <hermes>` | `cli/clawctl/agent/sync.py:sync` → `sync_agent_canonical` → `render_hermes` → SSH copy | canonical `.canonical.j2` | ✅ works (post-#621/#624) |
| `clawctl agent configure <hermes>` | `cli/clawctl/agent/configure.py:configure` → `lifecycle.sync_agent` (legacy) → `configure_agent` → ansible `configure.yaml` → `ansible.builtin.template:` | **legacy `.j2`** | ❌ broken — single-provider only |
| `clm agent sync <hermes>` (legacy `clm`, not shipped as console script per `pyproject.toml`) | `cli/agent.py:cmd_sync` → same legacy `lifecycle.sync_agent` | legacy `.j2` | ❌ broken |

So today: `sync` is right; `configure` is broken; the legacy `clm`
surface is a duplicate broken path that ships only via developer
imports.

This is the duplication the user wants gone.

---

## 2. Approach

### 2.1 Render-and-copy inside `configure_agent`

In `lifecycle.configure_agent`, when `resolved_type == "hermes"`:

1. Call `build_render_inputs(unix_agent_name)` and then
   `render_hermes(inputs)`. Returns `RenderedFiles({".hermes/.env":
   <bytes>, ".hermes/config.yaml": <bytes>})`.
2. Write the two rendered bodies to a temp dir on the clawctl machine
   (e.g. via `tempfile.TemporaryDirectory`), in a structure the
   playbook can pick up.
3. Pass the temp dir path to ansible via `extra_vars["rendered_hermes_dir"]`.
4. In `configure.yaml` and `configure_macos.yaml`, replace the two
   `template:` tasks with `copy:` tasks reading from
   `{{ rendered_hermes_dir }}/.env` and `.../config.yaml`. Same
   `dest`, `owner`, `group`, `mode`, `force: yes`, `no_log: true`,
   `notify: Restart hermes service`.

The temp dir is cleaned up by the `TemporaryDirectory` context manager
after the playbook run returns. `extra_vars` already carries a dict
through to ansible-runner, so this is a one-line addition.

### 2.2 Delete the legacy templates

```
git rm src/clawrium/platform/registry/hermes/templates/hermes-config.yaml.j2
git rm src/clawrium/platform/registry/hermes/templates/hermes.env.j2
```

### 2.3 Delete legacy `lifecycle.sync_agent` and legacy `clm agent sync`

After §2.1, the production `clawctl agent configure` no longer calls
`lifecycle.sync_agent` (it calls `configure_agent` directly, which now
routes hermes through `render_hermes`).

Audit remaining `lifecycle.sync_agent` callers:

- `src/clawrium/cli/agent.py:2640` (legacy `clm agent sync`) — delete
  the `cmd_sync` function and its `agent_app.command()` registration.
- `src/clawrium/cli/clawctl/agent/configure.py:27` — the import is
  unused after §2.1 wires `configure` to `configure_agent` directly.
  Drop the import.
- `src/clawrium/core/lifecycle_macos.py:721-738` (`sync_agent` macOS
  shim) — delete the shim and its caller chain.
- Tests under `tests/cli/clawctl/agent/test_sync_*.py` and
  `tests/core/test_lifecycle_macos*.py` — rewrite or delete (see §3).

Then delete `lifecycle.sync_agent` itself (`lifecycle.py:1169`).

### 2.4 Prune `tests/test_hermes_configure.py`

3000+ lines, four references to the deleted templates (lines 64, 81,
2017, 3004). The template-rendering tests are duplicates of what
`tests/core/test_render.py` covers post-#624. Delete the template
assertions. Keep tests that drive the playbook tasks for
mcp_servers verification, gh auth, ~/.gitconfig.

If after pruning <500 lines remain, fold the survivors into a
narrower `tests/test_hermes_configure_playbook.py` and delete the
old file.

### 2.5 Decouple zeroclaw from hermes references

`src/clawrium/platform/registry/zeroclaw/templates/zeroclaw-env.conf.j2`:

- Line 21: `# Mirrors hermes/hermes.env.j2:115-122.` — replace with a
  zeroclaw-native comment describing the GITHUB_TOKEN write rule on
  its own terms.
- Line 53: `…Mirrors hermes hermes.env.j2:111-114. #}` — same. State
  the zeroclaw invariant without referencing hermes.

Multi-provider is a hermes-only feature; zeroclaw's env template is
zeroclaw's only and should read that way.

### 2.6 AGENTS.md

Add one short paragraph to the hermes section:

> **Hermes config rendering.** `~/.hermes/config.yaml` and
> `~/.hermes/.env` are rendered exclusively by
> `src/clawrium/core/render.py:render_hermes`. The ansible playbook
> copies the pre-rendered bytes; it does not template them. Change the
> on-host shape by editing the canonical `.j2` files in
> `src/clawrium/platform/registry/hermes/templates/` and the
> `render_hermes` plumbing — there is no second template path.

No lockstep paragraph; no two-template-family note. Just one path.

### 2.7 CHANGELOG `[Unreleased]`

```
### Changed

- hermes: `~/.hermes/config.yaml` and `~/.hermes/.env` are now rendered
  client-side by `clawctl` (via `render_hermes`) and copied to the
  agent host by the configure playbook, instead of being templated
  server-side by ansible. This unifies the rendering path between
  `clawctl agent configure` and `clawctl agent sync`, so multi-provider
  attachments now work on both commands (previously only `sync`
  rendered them correctly — see #622). No operator action required.

### Removed

- hermes: legacy ansible-side templates
  `src/clawrium/platform/registry/hermes/templates/hermes-config.yaml.j2`
  and `hermes.env.j2`. They are superseded by the canonical
  `hermes-config.canonical.yaml.j2` and `hermes-env.canonical.j2` used
  by `render_hermes`.
- legacy `lifecycle.sync_agent` and the legacy `clm agent sync`
  command surface (`cli/agent.py:cmd_sync`). The shipped
  `clawctl agent sync` (canonical pipeline) is unchanged.
```

No `### BREAKING` section: the operator-visible commands keep their
exact contract. The removals only affect downstream code that imports
the deleted symbols directly — none of those callers exist outside
this repo (verified by grep).

### 2.8 Files to modify / delete

Modify:

- `src/clawrium/core/lifecycle.py` — wire `configure_agent` to call
  `render_hermes` + temp-dir + extravars when hermes; delete
  `sync_agent` after.
- `src/clawrium/platform/registry/hermes/playbooks/configure.yaml`
- `src/clawrium/platform/registry/hermes/playbooks/configure_macos.yaml`
- `src/clawrium/cli/clawctl/agent/configure.py` — drop the
  `sync_agent` import; call `configure_agent` directly.
- `src/clawrium/core/lifecycle_macos.py` — drop the `sync_agent` shim.
- `src/clawrium/platform/registry/zeroclaw/templates/zeroclaw-env.conf.j2` — drop hermes refs in comments.
- `AGENTS.md` — one paragraph (§2.6).
- `CHANGELOG.md` — `[Unreleased]` (§2.7).
- `tests/test_hermes_configure.py` — prune (§2.4).
- `tests/cli/clawctl/agent/test_sync_*.py` — rewrite against
  `sync_agent_canonical` or delete.
- `tests/core/test_lifecycle_macos*.py` — drop `monkeypatch` on the
  deleted symbol; rewrite to patch `configure_agent` if still relevant.

Delete:

- `src/clawrium/platform/registry/hermes/templates/hermes-config.yaml.j2`
- `src/clawrium/platform/registry/hermes/templates/hermes.env.j2`
- `src/clawrium/cli/agent.py:cmd_sync` (function + decorator
  registration only — the file has other commands that stay).

---

## 3. Migration

**Operator-facing migration: none.** Every `clawctl` command keeps its
contract:

- `clawctl agent configure <name>` — same args, same stages, same
  exit codes. Internals change; output is byte-identical for
  single-provider hermes (verified by snapshot tests #2 below). For
  multi-provider hermes the output now includes `auxiliary.<role>:`
  blocks that were silently missing before.
- `clawctl agent sync <name>` — unchanged.
- `clawctl agent restart <name>` — unchanged.

**Developer-facing migration:**

- Anyone importing `clawrium.core.lifecycle.sync_agent` directly:
  switch to `lifecycle_canonical.sync_agent_canonical` (the production
  sync path) or `lifecycle.configure_agent` (the production configure
  path).
- Anyone vendoring `hermes-config.yaml.j2` or `hermes.env.j2` as
  template inputs: switch to calling `render_hermes` and reading its
  `RenderedFiles` output.

CHANGELOG documents both in `### Removed` (§2.7) without a `### BREAKING`
header (no operator action required).

---

## 4. Tests

### 4.1 Automated

1. **Existing canonical snapshot tests** (`tests/core/test_render.py`,
   from #624) keep passing — no template change; just delete-and-route.
2. **New snapshot test for `configure_agent` hermes path**: assert
   that `configure_agent` for a single-provider hermes writes
   byte-identical content to what `render_hermes` produces (regression
   pin — the rewrite must not drift).
3. **New integration-style test**: `configure_agent` for a
   multi-attachment hermes (primary + 1 aux openrouter + 1 aux
   bedrock) produces a temp dir whose `config.yaml` contains exactly
   the `auxiliary.<role>:` blocks the canonical template emits, and
   the env file carries one `<TYPE>_API_KEY=` per non-primary type +
   the AWS triple.
4. **Removed-import test**: `from clawrium.core.lifecycle import
   sync_agent` raises `ImportError`. Documents the developer-facing
   break flagged in CHANGELOG `### Removed`.

`make test && make lint`.

### 4.2 UAT (operator-run, real hosts)

Targets: `wolf-i` (linux) and `mac-test` (macOS, 100.120.88.97). Setup
once: `clawctl host create … --alias wolf-i`, `clawctl agent create
maurice --type hermes --host wolf-i`, and providers
`test-anthropic` / `test-openrouter` / `test-bedrock`.

| # | Scenario | Steps | Expected |
|---|---|---|---|
| 1 | Single-provider configure (regression) | attach `test-anthropic --role primary` → `clawctl agent configure maurice` → cat `~/.hermes/config.yaml`, `.env` | `model.provider: anthropic`, `auxiliary.title_generation.model: claude-haiku-4-5-20251001`; `.env` has exactly one `ANTHROPIC_API_KEY=`. **Byte-identical to pre-PR.** |
| 2 | **Multi-provider configure (the bug)** | also attach `test-openrouter --role compression` → `configure` → cat the two files | `config.yaml` has `auxiliary.compression: { provider: openrouter, model: … }`; `.env` has both `ANTHROPIC_API_KEY=` and `OPENROUTER_API_KEY=`. **This is what fails on main today.** |
| 3 | Multi-provider sync parity | `clawctl agent sync maurice` → cat the file | Byte-identical to UAT 2. `sync` and `configure` produce the same file. |
| 4 | Daemon picks up aux | `clawctl agent start maurice` → `clawctl agent chat maurice` (trigger title-gen) → `journalctl -u hermes-maurice` | No 401s, no "auxiliary not configured"; aux slot invoked when matching task fires. |
| 5 | Bedrock aux + AWS triple | attach `test-bedrock --role title_generation` → `configure` → grep `.env` for `AWS_` and `_API_KEY` | `AWS_ACCESS_KEY_ID/_SECRET_ACCESS_KEY/_DEFAULT_REGION` present alongside the two `*_API_KEY=` lines; `config.yaml`'s `auxiliary.title_generation` shadows the upstream default (operator intent wins). |
| 6 | Conflict detection (loud) | create `test-openrouter-2` with different key → attach `--role planning` → `configure` | `AgentConfigError: same-type providers with different API keys …` at assembly time. Nothing pushed to host. |
| 7 | macOS path | repeat UAT 1 + UAT 2 on `mac-test` | Same behavior; `configure_macos.yaml`'s `copy:` task lands bytes at `/Users/maurice/.hermes/…`. |
| 8 | Restart preserves config | `clawctl agent restart maurice` → cat `config.yaml` | Unchanged from UAT 5. Restart does not re-render. |
| 9 | Operator commands unchanged | run each: `configure --stage providers/identity/validate`, `sync`, `sync --workspace`, `sync --dry-run --diff` | All run; same flags / output shape as before. `--dry-run --diff` shows zero drift after a fresh `configure`. |
| 10 | Legacy import removed | `python -c "from clawrium.core.lifecycle import sync_agent"` | `ImportError`. |
| 11 | Zeroclaw untouched | create + configure + start + chat a zeroclaw agent; grep `zeroclaw-env.conf.j2` for "hermes" | All zeroclaw ops work as before; zero "hermes" occurrences in the zeroclaw template. |
| 12 | Legacy templates not shipped | `uv pip show -f clawrium \| grep -E "hermes-config\.yaml\.j2\|hermes\.env\.j2"` | No matches. Only `.canonical.j2` files ship. |

**Pass criteria:** all 12 green, `make test` + `make lint` clean, and
`clawctl agent doctor maurice` reports zero drift after each
configure/sync.

**Sign-off:** operator validates **UAT 2 + UAT 4 + UAT 7** on real
hosts (wolf-i + mac-test). The rest can be CI/unit-test gated, but
those three need eyes on a daemon-rendered config file to close the
original wolf-i repro.

---

## 5. Risks

### 5.1 Configure playbook tasks that read the file post-render

`configure.yaml:205-239` greps the rendered `.env` for
`^OPENROUTER_API_KEY=` etc. Those tasks read whatever file landed in
`/home/<name>/.hermes/.env` regardless of how it got there, so they
keep working — the env-var keys `render_hermes` emits are
byte-identical to what the legacy template emitted for the
single-provider case. Multi-provider was never validated by these
greps anyway. Low risk; covered by test #2.

### 5.2 macOS path

`configure_macos.yaml:54-66` mirrors the linux template tasks. Same
treatment. mac-test host (see memory `[[mac_test_host]]`) is the
verification target. `lifecycle_macos.py:721-738` delegates to
`lifecycle.sync_agent`; this gets rewritten to delegate to
`configure_agent` directly when the macOS configure dispatcher is in
play.

### 5.3 Temp-dir + extravars plumbing

Ansible-runner accepts `extravars` as a dict; the temp-dir path
becomes one string entry. Risk: the playbook runs on the **agent
host**, not the clawctl host — so `copy:` with a `src:` path resolves
against the **controller** (clawctl) by default, which is correct
here. Verify on first run that the `copy:` task does not try to read
from the remote host's filesystem. The Ansible doc contract for
`ansible.builtin.copy` is `src` = controller, `dest` = remote.

### 5.4 Onboarding state transitions and READY write

`configure_agent` is also the gate that flips agents to READY (the
lifecycle transition at `lifecycle.py:1380-1438`). Rewiring its hermes
render does not move that logic; only the render step changes. Low
risk.

### 5.5 Legacy `clm` CLI's continued existence

The legacy `clm` (cli/main.py) is not the shipped console script per
`pyproject.toml`, but it's "still imported by the existing test
suite" per the cli/__init__.py docstring. Deleting `cmd_sync` may
break tests that import the legacy `agent_app`. The fix is the prune
in §2.4. If the legacy `clm` itself becomes empty after this work,
that's a follow-up cleanup, out of scope here.

---

## 6. Steps

1. Audit grep: `grep -rn 'lifecycle\.sync_agent\|from clawrium.core.lifecycle import.*sync_agent' src/ tests/` — capture every caller (already done; results in §1).
2. Rewire `lifecycle.configure_agent` hermes branch to call
   `render_hermes` + temp-dir + extravars (§2.1).
3. Rewrite the two `template:` tasks in `configure.yaml` and
   `configure_macos.yaml` as `copy:` tasks (§2.1).
4. Wire `cli/clawctl/agent/configure.py` to call `configure_agent`
   directly; drop `sync_agent` import.
5. Run `make test` against single-provider hermes fixtures; confirm
   byte-identical output (test #2).
6. Add multi-attachment test (#3).
7. Delete `cli/agent.py:cmd_sync`, `lifecycle_macos.py:sync_agent`,
   `lifecycle.sync_agent`.
8. Delete the two legacy `.j2` files.
9. Prune `tests/test_hermes_configure.py` and the
   `tests/core/test_lifecycle_macos*.py` patches on the deleted
   symbol.
10. Strip hermes references from
    `zeroclaw-env.conf.j2` comments.
11. AGENTS.md paragraph (§2.6).
12. CHANGELOG `[Unreleased]` entries (§2.7).
13. `make test && make lint` (covers §4.1).
14. Run UAT §4.2 on wolf-i (linux) and mac-test (macOS). Sign-off
    requires UAT 2 + UAT 4 + UAT 7 verified on a real daemon.
15. Open PR; close #622.

## Subtasks

None — per orchestrator handoff notes.

---

<details>
<summary>Prompt Log</summary>

## Stage 1 — planning (initial, pre-#621 merge)

**Stage**: planning
**Skill**: /itx:plan-create
**Timestamp**: 2026-06-05T00:00:00Z
**Model**: claude-opus-4-7

```prompt
/itx-plan-create 622  (canonical-template multi-provider rendering; plan-only)
```

## Stage 2 — planning (revised after #621 merge)

```prompt
621 is merged. update plan
```

## Stage 3 — planning (final, kill legacy path)

**Stage**: planning-final
**Skill**: /itx:plan-create
**Timestamp**: 2026-06-06T00:00:00Z
**Model**: claude-opus-4-7

```prompt
get rid of all legacy paths. the new one is the canonical path and only
source of truth. update changelog instructions and instructions in this
issue for manual migration.

zeroclaw should not refer to hermes in any way. remove dead code and
cleanup paths. adding multiple providers is just hermes functionality.
```

**Output**: this revision of `.itx/622/00_PLAN.md` and a follow-up
comment on issue #622 summarizing the final scope.

</details>
