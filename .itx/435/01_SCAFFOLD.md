# Issue #435 — Execution Scaffold (`clawctl` UX sweep)

GitHub: https://github.com/ric03uec/clawrium/issues/435
Plan: [`00_PLAN.md`](00_PLAN.md)

---

## Execution strategy: stacked branches in a worktree, single merge to main

The whole issue is delivered as **one long-lived integration branch in a
worktree** with five stacked bundle branches layering on top of it. `main`
is not touched until end-to-end validation on the integration branch is
green.

### Worktree + branch layout

```
~/workspace/ric03uec/clawrium-issue-435/    # git worktree (per AGENTS.md convention)
└── branch: feat/435-clawctl-ux             # long-lived integration branch off main
        ├── feat/435/bundle-1-audit-before  # → merges into feat/435-clawctl-ux
        ├── feat/435/bundle-2-foundation    # → merges into feat/435-clawctl-ux
        ├── feat/435/bundle-3-host-agent    # → merges into feat/435-clawctl-ux
        ├── feat/435/bundle-4-attachables   # → merges into feat/435-clawctl-ux
        └── feat/435/bundle-5-templates-docs-audit-after
                                            # → merges into feat/435-clawctl-ux

When ALL bundles merged + end-to-end gate green:
    feat/435-clawctl-ux  ─►  main         (single PR, single merge)
```

### Stacking rules

1. **Integration branch first.** Create `feat/435-clawctl-ux` off `main` in the worktree before any bundle work.
2. **Each bundle branches off the previous bundle's tip** (not the integration branch directly), so commits stack linearly and review of bundle N only shows bundle N's changes.
3. **Each bundle PR targets the integration branch**, not `main`. Sub-issue tracks the bundle; PR closes the sub-issue.
4. **Bundle PRs may merge into the integration branch as they're approved** — no need to wait for the full stack. The integration branch always reflects "everything green so far."
5. **After all 5 bundles merged into integration**, run the End-to-End Validation Gate (see bottom of this file). Only then is the integration → main PR opened.
6. **No `main` commits at any point during execution.** Even hotfixes go through the integration branch.

### Why stacked, not parallel

The 10-phase scaffold (preserved as Appendix A) noted that P2..P8 could
parallelize. Stacked execution sacrifices that parallelism to:

- Eliminate merge conflicts in `cli/__init__.py` and Typer group registration (top of Risk Register, item R2).
- Make each bundle's review boundary clean — bundle 4's PR only shows attachable code, not foundation code.
- Allow a single end-to-end smoke run on the final integration branch rather than per-bundle ones against `main`.

---

## Bundle 1 — wolf-i audit-before (regression baseline)

**Branch:** `feat/435/bundle-1-audit-before` (off `feat/435-clawctl-ux`)
**Phases:** P0
**Depends on:** Plan PR #505 merged.
**Sub-issue title:** `[Parent #435] Bundle 1: wolf-i audit-before (regression baseline)`

### Goal

Capture a verbatim, frozen snapshot of every read-only `clm` command and one
full lifecycle transcript per agent type against a clean wolf-i fleet, so
Bundle 5's audit-after can diff against it line-by-line.

### Specific outcomes to validate

Done when ALL of the following are true:

- [ ] **File exists:** `.itx/435/audit-before.md` is committed on the integration branch (via Bundle 1's PR).
- [ ] **Header block present:** file starts with `clm --version` output, `uv tool list` showing the installed clawrium version, wolf-i host details (alias, address, SSH user), and the UTC timestamp at the start of capture.
- [ ] **All three agent types installed on wolf-i:** `clm agent ps` output captured shows one `zeroclaw`, one `hermes`, one `openclaw` agent, each with status `running`.
- [ ] **Read-only command transcripts captured** — one section per command, each showing the exact command run and its verbatim stdout+stderr+exit code:
  - `clm init` (no-op invocation to capture)
  - `clm ps`
  - `clm host list`, `clm host ps wolf-i`
  - `clm agent ps`
  - `clm agent registry list`, `clm agent registry show zeroclaw`, `... hermes`, `... openclaw`
  - `clm provider list`, `clm provider types`
  - `clm integration list`, `clm integration types`
  - `clm skill list`, `clm skill show clawrium/tdd`
  - Per agent: `clm agent secret list <a>`, `clm agent memory show <a>`, `clm agent integration list <a>`, `clm agent skill list <a>`, `clm agent logs <a> --tail 20`
- [ ] **Lifecycle transcripts captured** — one section per agent type, each showing the full sequential transcript of: `agent install`, `agent configure` (defaults accepted; Discord/Slack skipped), `agent start`, `agent sync`, `agent stop`, `agent restart`.
- [ ] **Teardown verified:** final section shows `clm agent remove <a>` for each agent and a final `clm agent ps` empty result.
- [ ] **wolf-i clean state confirmed:** `clm host ps wolf-i` shows no agents at end-of-capture.
- [ ] **Markdown valid:** file renders correctly on GitHub (preview verified before PR open).

### Files affected (write-only)

- `.itx/435/audit-before.md` — new.

### Risks

- **wolf-i unreachable** at execution time → block; do not synthesize output.
- **`clm agent configure` prompts** for Discord/Slack → answer "skip" / leave empty for baseline; channels are first captured against `clawctl channel registry create` in Bundle 5.

### Complexity

simple (data capture only).

---

## Bundle 2 — clawctl foundation + service/meta commands

**Branch:** `feat/435/bundle-2-foundation` (off `feat/435/bundle-1-audit-before`)
**Phases:** P1 + P2
**Depends on:** Bundle 1 merged into integration branch.
**Sub-issue title:** `[Parent #435] Bundle 2: clawctl foundation + service/meta commands`

### Goal

Land the `clawctl` entrypoint, the shared output-rendering module, the
complete top-level Typer app skeleton (all groups registered, unimplemented
subcommands stubbed), and the system-level `service` + meta verbs.

### Specific outcomes to validate

#### Entrypoint

- [ ] **`pyproject.toml` script entry:** `[project.scripts]` contains `clawctl = "clawrium.cli:app"` (or equivalent). The `clm` entry is **removed** (no alias).
- [ ] **`uv tool install -e .` from worktree root succeeds**, and `which clawctl` returns a non-empty path while `which clm` returns nothing on the dev machine (after uninstalling old `clm`).
- [ ] **`clawctl --help` exit code 0** and output lists exactly these top-level commands/groups: `service`, `version`, `completion`, `tui`, `gui`, `host`, `agent`, `provider`, `channel`, `integration`, `skill`, `mcp`.
- [ ] **`clawctl --version` and `clawctl version`** both print the same version string and exit 0.
- [ ] **Every group's `--help` exit 0**, even ones whose subcommands stub to "not implemented" (proves top-level Typer registration is complete; closes Risk R2).

#### Output module (`src/clawrium/cli/output/`)

- [ ] **Module exists** with files: `table.py`, `json_yaml.py`, `stream.py`, `errors.py`, `age.py`, `status.py`.
- [ ] **Tabwriter test:** unit test feeds rows of varying widths to `table.render()` and asserts (a) every column is padded to the max width in that column, (b) the gap between columns is exactly 3 spaces, (c) no trailing whitespace.
- [ ] **`-o name` test:** asserts output is `<kind>/<name>` one per line, no header, no padding.
- [ ] **`-o json` test:** asserts output parses as a JSON array of objects with `snake_case` keys; timestamps are RFC3339 UTC; `age_seconds` is int.
- [ ] **`-o yaml` test:** asserts `yaml.safe_load(out) == json.loads(out_json)` for the same data set.
- [ ] **`-o wide` test:** asserts wide-mode includes the extra columns named in plan §6.3.
- [ ] **`--no-headers` test:** asserts header row is absent and column widths are still computed from data rows.
- [ ] **AGE formatter tests:** boundary table — 0s→`0s`, 59s→`59s`, 60s→`1m`, 3599s→`59m`, 3600s→`1h`, 86399s→`23h`, 86400s→`1d`, 8640000s→`100d`.
- [ ] **STATUS test:** every token in plan §6.13 maps to its TTY color when `force_color=True`; non-TTY (or `NO_COLOR=1`) emits raw token without ANSI codes.
- [ ] **NDJSON streamer test:** consecutive `emit()` calls produce one JSON object per line on stdout, each with `resource`, `phase`, `state`, `ts` keys.
- [ ] **Error formatter test:** `error("foo", hint="bar")` writes `Error: foo\nHint:  bar\n` to **stderr** and the process exits with non-zero code (asserted via `pytest` `SystemExit`).

#### `service` group

- [ ] **`clawctl service init`** runs the same setup as today's `clm init` (creates `~/.config/clawrium/` if missing; emits the same end-of-init success line).
- [ ] **`clawctl service start`**, **`stop`**, **`snapshot`** each print exactly `Not implemented: service <verb>` on stdout and exit 0. (Matches `clm snapshot` of today.)

#### Meta + rebrand

- [ ] **`clawctl completion bash`** emits a shell-completion script whose first line is the standard Typer/click completion preamble; same for `zsh` and `fish`. Output captured by `eval` in a subshell does not raise.
- [ ] **`clawctl tui`** launches the same TUI as `clm tui` did (verified by smoke: process starts, header banner shows `clawctl`, Ctrl-C exits 0).
- [ ] **`clawctl gui --no-open`** starts the GUI server on the default port without auto-opening a browser (verified by hitting `http://localhost:<port>/` and getting 200).

#### Test + lint

- [ ] `make test` passes (new tests in `tests/cli/output/`, `tests/cli/test_service.py`, `tests/cli/test_meta.py`; existing tests still green).
- [ ] `make lint` passes.

#### Negative checks (must FAIL — proves clean break)

- [ ] **`clm --help`** returns "command not found" (proves the rename, not an alias).
- [ ] No references to `clm = "clawrium.cli:app"` (or similar) remain in `pyproject.toml`.

### Files affected

- `pyproject.toml` — script entry.
- `src/clawrium/cli/__init__.py` — new top-level Typer app + group registry.
- `src/clawrium/cli/output/{table,json_yaml,stream,errors,age,status}.py` — new.
- `src/clawrium/cli/service.py`, `meta.py`, `tui.py`, `gui.py` — new (rebrand wrappers for tui/gui).
- `tests/cli/output/`, `tests/cli/test_service.py`, `tests/cli/test_meta.py` — new.

### Complexity

moderate.

---

## Bundle 3 — clawctl host + agent (Pattern B targets)

**Branch:** `feat/435/bundle-3-host-agent` (off `feat/435/bundle-2-foundation`)
**Phases:** P3 + P4
**Depends on:** Bundle 2 merged into integration branch.
**Sub-issue title:** `[Parent #435] Bundle 3: clawctl host + agent (Pattern B targets)`

### Goal

Implement the full Pattern-B target surface: `host` subtree and `agent`
subtree (CRUD + lifecycle + redefined `sync`). Discord/Slack prompts in
`agent configure` are preserved as TTY-only fallback during this bundle —
Bundle 4 extracts them.

### Specific outcomes to validate

#### `host` surface (per plan §4)

- [ ] **`clawctl host create <h> --user U [--port P] [--alias A] [--bootstrap]`** creates entry in `hosts.json` AND (with `--bootstrap`) runs the host bootstrap playbook. Re-running without `--bootstrap` is idempotent.
- [ ] **`clawctl host get`** default output is a kubectl table with columns `NAME ADDRESS USER STATUS AGE`. `-o yaml|json|wide|name` all return correctly-shaped output (verified by a parameterized test).
- [ ] **`clawctl host get -l env=prod`** filters by label.
- [ ] **`clawctl host describe <h>`** human-readable text format like §6.7; `-o yaml` returns the structured form.
- [ ] **`clawctl host delete <h>`** prompts for confirm on TTY, fails on non-TTY without `--yes`, succeeds on non-TTY with `--yes`. Removes entry from `hosts.json`.
- [ ] **`clawctl host edit <h> --user newuser`** updates the user in place.
- [ ] **`clawctl host reset <h> --yes`** wipes remote `xclm` state but keeps local record (distinct from delete; outcome verified by SSH'ing to host and confirming `xclm` home cleaned).
- [ ] **`clawctl host alias <h> --add foo --add bar --list`** shows both aliases; `--remove foo` removes one.
- [ ] **`clawctl host address <h> add 10.0.0.1`**, **`set-primary 10.0.0.1`**, **`get`**, **`delete 10.0.0.1`** all work.
- [ ] **`clawctl host label <h> env=prod role=web`** sets labels; **`env-`** removes one.
- [ ] **`clawctl host registry get`** prints placeholder content + exit 0.

#### `agent` Pattern-B surface (per plan §4)

- [ ] **`clawctl agent create <name> --type T --host H --provider P --yes`** runs without prompts on non-TTY, completes install + initial configure stage, returns exit 0.
- [ ] **`clawctl agent get`** default columns: `NAME TYPE HOST PROVIDER STATUS AGE` (matches §6.2 sample byte-for-byte after substituting real data). `-o wide` includes `ADDRESS PORT VERSION INSTALLED` per §6.3.
- [ ] **`clawctl agent describe <name>`** matches §6.7 layout (Name/Kind/Type/Version/Host/Provider/Status/Age/Installed + Config + Skills + Integrations + Channels + Onboarding sections present).
- [ ] **`clawctl agent edit <name>`** opens `$EDITOR` on the YAML record; on save, validates and persists.
- [ ] **`clawctl agent delete <name> --yes`** runs remote cleanup + removes local record.
- [ ] **`clawctl agent configure <name> --stage validate`** runs validate stage non-interactively.
- [ ] **Non-interactive contract enforced:** `clawctl agent configure <n>` with **stdin closed** and a missing required flag emits `Error: missing required flag --provider` (or similar) and exits non-zero. With stdin a TTY, the prompt fallback still works.
- [ ] **`clawctl agent start|stop|restart <n>`** each emit one streaming line per phase (per §6.8), exit 0 on success.
- [ ] **`clawctl agent sync <n>`** runs the 5-step redefined sync per §9: validate → push → restart → re-pair → verify. Output matches §6.10 sample (5 streaming lines + final `synced (drift=0, took Xs)`). Default `--timeout 120` enforced; `--dry-run` prints diff without push; `--workspace` skips restart; `--skip-validate` bypasses step 1.
- [ ] **`clawctl agent sync <n> -o json`** emits 5 NDJSON lines matching the schema in §6.9.
- [ ] **`clawctl agent logs <n> --tail 3`** matches §6.11 layout; `-o json` returns NDJSON.
- [ ] **`clawctl agent chat <n> --once "hello"`** sends one message and exits.
- [ ] **`clawctl agent open <n>`** opens the agent's web UI (only for agents whose manifest declares `features.web_ui`).
- [ ] **`clawctl agent port-forward <n> 8080:80`** opens the forward; Ctrl-C exits cleanly.
- [ ] **`clawctl agent exec <n> -- echo hi`** prints `Not implemented: agent exec` and exits 0.
- [ ] **`clawctl agent registry get`** lists supported types; **`describe zeroclaw`** shows the type's details.

#### Action-streaming + error contract

- [ ] Every lifecycle command (`create/start/stop/restart/sync/delete`) emits at least one streaming line per phase to stdout; errors go to stderr starting with `Error: ` and include a `Hint: ` line when applicable; exit code is non-zero.
- [ ] `-o json` on any lifecycle command produces NDJSON only on stdout; human-readable prose is suppressed.

#### Test + lint

- [ ] `make test` passes (new tests in `tests/cli/host/`, `tests/cli/agent/`; existing tests still green).
- [ ] `make lint` passes.
- [ ] **One real wolf-i integration test** per agent type: `pytest tests/integration/test_clawctl_lifecycle.py` runs `clawctl agent create → configure → start → sync → describe → delete` against the live wolf-i fleet and asserts each step succeeds. (This test is the bundle's "real world" gate; it's gated behind a `CLAWCTL_REAL=1` env var so CI doesn't run it.)

#### BEFORE→AFTER mappings verified (subset for this bundle)

- [ ] Every `host *` row in plan §5 table works as documented (smoke test that runs each `After (clawctl)` command and asserts exit 0).
- [ ] Every `agent *` row in plan §5 that doesn't involve attachables / sub-resources works as documented.

### Files affected

- `src/clawrium/cli/host/{create,get,describe,delete,edit,reset,alias,address,label,registry}.py` — new.
- `src/clawrium/cli/agent/{create,get,describe,delete,edit,configure,start,stop,restart,sync,logs,chat,open,port_forward,exec,registry}.py` — new.
- `tests/cli/host/`, `tests/cli/agent/`, `tests/integration/test_clawctl_lifecycle.py` — new.

### Complexity

complex (largest single bundle).

### Risks

- **R3 (carry-over):** Discord/Slack prompts remain in `agent configure` at end of this bundle. Block Bundle 5 docs claim ("CLI is fully non-interactive") until Bundle 4 has extracted them.

---

## Bundle 4 — Pattern A attachables (provider/channel/integration/skill/mcp) + agent sub-resources (secret/memory)

**Branch:** `feat/435/bundle-4-attachables` (off `feat/435/bundle-3-host-agent`)
**Phases:** P5 + P6 + P7
**Depends on:** Bundle 3 merged into integration branch.
**Sub-issue title:** `[Parent #435] Bundle 4: Pattern A attachables + agent sub-resources`

### Goal

Wire every Pattern A attachable through its `registry` CRUD + per-agent
`attach/detach/get`, introduce the brand-new `channel` noun (including the
one allowed `core.*` addition for channel storage), extract Discord/Slack
prompts from `agent configure`, and ship per-agent `secret` + `memory`
sub-resources.

### Specific outcomes to validate

#### `provider registry`

- [ ] **`clawctl provider registry create <name> --type anthropic --api-key K`** non-interactively creates an entry in `providers.json`.
- [ ] `--api-key-stdin`, AWS triplet (`--access-key`, `--secret-key`, `--region`), and `--ollama-url U` flag paths all work; smoke test for each provider type.
- [ ] `get|describe|delete|edit|refresh` all work with `-o table|json|yaml|wide|name` for `get`/`describe`.
- [ ] **`clawctl agent provider attach <name> --agent <a>`** writes provider ref into agent record; `detach` removes it; `get --agent <a>` returns current attachment.

#### `channel registry` (NEW)

- [ ] **New file:** `~/.config/clawrium/channels.json` is created on first `channel registry create`. Schema matches plan §8 exactly.
- [ ] **New core module:** `src/clawrium/core/channels.py` exists (the one deliberate `core.*` addition; documented in the bundle PR description).
- [ ] **`clawctl channel registry create my-discord --type discord --token T --allowed-user 123 --allowed-channel 456 --require-mention`** runs non-interactively, persists encrypted token.
- [ ] Slack path: `--type slack --token T --app-token X --home-channel C --stream-mode replace --stream-delay 100` runs non-interactively.
- [ ] `--token-stdin` reads token from stdin.
- [ ] `get|describe|delete|edit` work; `edit` accepts the same flag set as `create`.
- [ ] **`clawctl agent channel attach my-discord --agent <a>`** writes the channel ref into the agent record; restart picks it up.
- [ ] **Discord/Slack prompts removed from `agent configure`:** grep across `src/clawrium/cli/agent/configure.py` returns zero `typer.prompt` calls related to Discord, Slack, bot tokens, allowed users, allowed channels, allowed guilds, home channel, require mention, stream mode, stream delay. (Codified as a test in `tests/cli/agent/test_configure_no_channel_prompts.py`.)
- [ ] **`clawctl agent configure <n> --stage channels`** either exits with a deprecation notice pointing to `clawctl channel registry create` + `clawctl agent channel attach`, or the `channels` stage is removed from the enum (decide and document in the PR).

#### `integration registry`

- [ ] **`clawctl integration registry create gh --type github --credential token=TKN`** runs non-interactively; `--credential-stdin` reads `KEY=VALUE` pairs from stdin.
- [ ] `get|describe|delete|edit` work.
- [ ] **`clawctl agent integration attach gh --agent <a>`**, `detach`, `get` all work.

#### `skill registry` (read-only)

- [ ] **`clawctl skill registry get`** lists all bundled skills with columns `NAME REGISTRY DESCRIPTION`.
- [ ] **`clawctl skill registry get -l registry=clawrium`** filters by namespace.
- [ ] **`clawctl skill registry describe clawrium/tdd`** shows full skill metadata.
- [ ] **`clawctl skill registry create`** does not exist as a subcommand (skill registry is read-only — verified by `clawctl skill registry --help`).
- [ ] **`clawctl agent skill attach clawrium/tdd --agent <a>`**, `detach`, `get` all work.

#### `mcp registry` (placeholder)

- [ ] **`clawctl mcp registry get`** prints `Not implemented: mcp registry` and exits 0.
- [ ] **`clawctl mcp registry describe foo`** same.

#### `agent secret`

- [ ] **`clawctl agent secret create FOO --agent <a> --value bar`** non-interactive; writes encrypted entry.
- [ ] **`--value-stdin`** reads value from stdin.
- [ ] **`--from-file <path>`** reads value from file (the single exception per plan §7).
- [ ] **`clawctl agent secret get --agent <a>`** lists secret keys (no values); `describe FOO --agent <a>` shows metadata; `delete FOO --agent <a> --yes` removes.
- [ ] **`clawctl agent secret import --agent <a> --from-file path/to/.env`** bulk-imports KEY=VALUE pairs.

#### `agent memory`

- [ ] **`clawctl agent memory get --agent <a>`** lists memory files; `--file F` shows content of one.
- [ ] **`clawctl agent memory describe <file> --agent <a>`** shows metadata.
- [ ] **`clawctl agent memory edit <file> --agent <a> --content "..."`** or `--from-file <p>` (the exception) updates the file.
- [ ] **`clawctl agent memory delete <file> --agent <a> --yes`** removes the file.

#### Non-interactive contract sweep (whole bundle)

- [ ] **`tests/cli/test_non_interactive.py`** runs every command added in bundles 2/3/4 with `stdin=DEVNULL` and a complete flag set; asserts every one exits 0 without blocking. This is the codified version of plan §7's hard rule.

#### BEFORE→AFTER mappings verified

- [ ] Every `provider *`, `integration *`, `skill *`, `agent secret *`, `agent memory *`, `agent integration *`, `agent skill *` row in plan §5 table works as documented.
- [ ] New rows that didn't exist in `clm`: `channel registry create|get|describe|delete|edit` and `agent channel attach|detach|get` all work as documented.

#### Test + lint

- [ ] `make test` passes (new tests in `tests/cli/{provider,channel,integration,skill,mcp}/`, `tests/cli/agent/test_secret.py`, `test_memory.py`, `tests/core/test_channels.py`).
- [ ] `make lint` passes.

### Files affected

- `src/clawrium/cli/{provider,channel,integration,skill,mcp}/` — new modules.
- `src/clawrium/cli/agent/{provider,channel,integration,skill,secret,memory}.py` — new per-agent subcommands.
- `src/clawrium/cli/agent/configure.py` — remove Discord/Slack prompts (the one core-CLI surgery).
- `src/clawrium/core/channels.py` — new (the one deliberate `core.*` addition; new module, no modification of existing).
- `tests/cli/{provider,channel,integration,skill,mcp}/`, `tests/cli/agent/test_secret.py`, `test_memory.py`, `tests/core/test_channels.py`, `tests/cli/test_non_interactive.py` — new.

### Complexity

complex (second-largest bundle).

### Risks

- **R1 (active):** `src/clawrium/core/channels.py` bumps against plan §2 guardrail ("`clawrium.core.*` untouched"). Mitigation: new file only (no modifications), documented in PR description, reviewed for blast radius.

---

## Bundle 5 — template rename + GUI strings + docs/blog/CHANGELOG + audit-after

**Branch:** `feat/435/bundle-5-templates-docs-audit-after` (off `feat/435/bundle-4-attachables`)
**Phases:** P8 + P9 + P10
**Depends on:** Bundle 4 merged into integration branch.
**Sub-issue title:** `[Parent #435] Bundle 5: templates + docs + audit-after`

### Goal

Apply the `<type>-` template prefix convention with a guard test, sweep all
user-visible `clm` strings to `clawctl` in the GUI and docs, write the
breaking-change blog post and CHANGELOG entry, then run the wolf-i
audit-after sweep and diff it against Bundle 1's audit-before.

### Specific outcomes to validate

#### Template rename + validation

- [ ] **Files renamed** (verified by `git log --diff-filter=R`):
  - `src/clawrium/platform/registry/zeroclaw/templates/clm-env.conf.j2` → `zeroclaw-env.conf.j2`
  - `src/clawrium/platform/registry/zeroclaw/templates/config.toml.j2` → `zeroclaw-config.toml.j2`
  - `src/clawrium/platform/registry/hermes/templates/config.yaml.j2` → `hermes-config.yaml.j2`
  - `src/clawrium/platform/registry/hermes/templates/.env.j2` → `hermes.env.j2`
- [ ] **Playbook refs updated:** `grep -r 'clm-env\.conf\|config\.toml\.j2\|config\.yaml\.j2\|\.env\.j2' src/clawrium/platform/registry/{zeroclaw,hermes}/playbooks/` returns zero matches (all references use new source names).
- [ ] **Destination filenames unchanged** on agent host (runtime-dictated): `/etc/systemd/system/zeroclaw-<n>.service.d/10-zeroclaw-env.conf`, `~/.zeroclaw/config.toml`, `~/.hermes/config.yaml`, `~/.hermes/.env`. Verified by SSH after wolf-i `clawctl agent sync` in audit-after.
- [ ] **New guard test:** `tests/platform/test_template_naming.py::test_no_clm_prefixed_templates` enumerates all `*.j2` files under `src/clawrium/platform/registry/*/templates/` and asserts none start with `clm-` and all start with `<type>-` or `<type>.`.

#### GUI strings sweep

- [ ] **Frontend source path identified** during execution (per plan §12 — frontend lives in this repo; exact path located).
- [ ] **Grep audit:** `grep -rn 'clm ' src/clawrium/gui/frontend/src/` (or wherever frontend source lives) returns zero matches except in deliberately-historical contexts (a comment marker like `// historical:` is acceptable and noted in PR review).
- [ ] **GUI rebuilt:** `_next/` artifact regenerated; `clawctl gui --no-open` serves the rebuilt artifact (verified by visiting `/` and seeing "clawctl" in the rendered HTML).
- [ ] **Backend docstrings scrubbed:** `grep -rn '"""[^"]*clm ' src/clawrium/` returns zero matches in user-facing help strings (Python imports referencing `clm` are fine — those weren't renamed).

#### Docs sweep

- [ ] **`README.md`** install commands show `clawctl`; the brief install section (per AGENTS.md "Installation Source of Truth") matches `docs/installation.md`.
- [ ] **`AGENTS.md`** updated: examples in "Quickstart" section use `clawctl`; the gateway token lifecycle section's command references (`clm agent configure/sync/restart`) renamed; web UI section's `clm agent open` renamed; "Quick Reference" workflow table commands renamed.
- [ ] **`CONTRIBUTING.md`** updated.
- [ ] **`docs/installation.md`** updated (canonical) and **`website/docs/installation.md`** mirrors it verbatim under the Docusaurus frontmatter (per AGENTS.md mirror rule).
- [ ] **Demo sweep:** `tmp/`, `demo.md`, `slides/`, all `website/blog/*.md` reviewed; `clm` replaced with `clawctl` except in:
  - `website/blog/2026-05-23-introducing-clawrium.md` (historical accuracy; preserved per plan §12).
  - Any commit-message blockquotes (frozen history).

#### Blog post + CHANGELOG

- [ ] **New blog post** at `website/blog/<YYYY-MM-DD>-clawctl-kubectl-ux.md` (or similar; final title at execution time) announces the rename, the kubectl-style verb grammar, and the breaking-change posture.
- [ ] **`CHANGELOG.md`** has a top-level `## BREAKING` section under the next version header listing:
  - Binary rename `clm` → `clawctl` (no alias).
  - Full BEFORE→AFTER command map (link to plan §5 in `.itx/435/00_PLAN.md`).
  - `channel` extraction from `agent configure` into `channel registry`.
  - Template renames (zeroclaw + hermes).
  - `sync` semantics: now drift-to-zero flush with default 2-min timeout.
- [ ] **No version bump in this issue** (per plan §12). `version` field in `pyproject.toml` and `AGENTS.md` "Version: ..." line unchanged.

#### wolf-i audit-after + regression diff

- [ ] **File exists:** `.itx/435/audit-after.md` committed on integration branch.
- [ ] **Same fleet topology as audit-before:** one zeroclaw, one hermes, one openclaw on wolf-i, each `running`. Verified by `clawctl agent get` at top of file.
- [ ] **Equivalent transcripts captured** — each read-only `clm` command from Bundle 1's audit gets its `clawctl` equivalent per plan §5 mapping; each lifecycle transcript gets the equivalent flag-driven invocation.
- [ ] **New transcripts added** for surface that didn't exist in `clm`: `clawctl channel registry create` for both Discord and Slack types; `clawctl agent channel attach`; `clawctl completion`.
- [ ] **Diff section** at the bottom of `audit-after.md` calls out, line by line, every intentional behavioral change vs `audit-before.md` (e.g., column header changes, AGE formatting, status vocabulary). Any unintentional diff blocks the bundle's PR.
- [ ] **wolf-i clean state confirmed** at end of audit-after capture.

#### Test + lint

- [ ] `make test` passes.
- [ ] `make lint` passes.
- [ ] `make format` produces zero diff on the integration branch.

### Files affected

- Template renames (4 files) + playbook ref updates.
- `src/clawrium/gui/frontend/**` — string replacements; `_next/` regenerated.
- `README.md`, `AGENTS.md`, `CONTRIBUTING.md`, `docs/installation.md`, `website/docs/installation.md`, `CHANGELOG.md`.
- `website/blog/<date>-clawctl-kubectl-ux.md` — new.
- `tests/platform/test_template_naming.py` — new.
- `.itx/435/audit-after.md` — new.

### Complexity

moderate.

---

## End-to-End Validation Gate (integration branch → main)

Run **only after all 5 bundle PRs have merged** into
`feat/435-clawctl-ux`. The integration → main PR may not open until every
item below is checked.

### Gate 1 — clean rebuild

- [ ] `uv tool uninstall clawrium && uv tool install -e .` from a fresh shell on the integration branch succeeds.
- [ ] `which clawctl` returns a path; `which clm` returns nothing.
- [ ] `clawctl --help` lists all 12 top-level commands/groups; every group's `--help` exits 0.

### Gate 2 — full test suite

- [ ] `make test` green from a clean `pytest` cache.
- [ ] `make lint` green.
- [ ] `make format` produces zero diff.
- [ ] `make test-cov` shows total coverage at or above the pre-issue baseline (record baseline in Bundle 1's PR for comparison).

### Gate 3 — wolf-i full-fleet end-to-end

Run live against wolf-i, capture transcript at `.itx/435/e2e-validation.md`:

- [ ] `clawctl service init` on a clean dev machine (no prior `~/.config/clawrium/`) succeeds.
- [ ] `clawctl host create wolf-i --user <u> --bootstrap` succeeds non-interactively.
- [ ] `clawctl provider registry create anthropic --type anthropic --api-key-stdin` (read from `pass` or env) succeeds.
- [ ] `clawctl channel registry create my-discord --type discord --token-stdin --allowed-user <id>` succeeds non-interactively (NEW path that didn't exist pre-issue).
- [ ] For each agent type {zeroclaw, hermes, openclaw}:
  - [ ] `clawctl agent create <name> --type <t> --host wolf-i --provider anthropic --yes` succeeds.
  - [ ] `clawctl agent configure <name> --stage validate` succeeds.
  - [ ] `clawctl agent channel attach my-discord --agent <name>` succeeds (channels-not-applicable agents may skip with documented error).
  - [ ] `clawctl agent skill attach clawrium/tdd --agent <name>` succeeds.
  - [ ] `clawctl agent secret create FOO --agent <name> --value bar` succeeds.
  - [ ] `clawctl agent start <name>` succeeds; `clawctl agent get` shows status `running`.
  - [ ] `clawctl agent sync <name>` completes in ≤2min, exits with `drift=0`.
  - [ ] `clawctl agent describe <name>` shows attached channel, skill, secret, provider.
  - [ ] `clawctl agent restart <name>` succeeds.
  - [ ] `clawctl agent logs <name> --tail 10` returns logs.
  - [ ] `clawctl agent stop <name>` → `clawctl agent get` shows status `stopped`.
  - [ ] `clawctl agent delete <name> --yes` removes the agent.
- [ ] `clawctl agent get` returns empty list after all agents deleted.
- [ ] `clawctl host reset wolf-i --yes` (optional) wipes wolf-i clean.

### Gate 4 — regression diff

- [ ] `.itx/435/audit-before.md` vs `.itx/435/audit-after.md` diff reviewed line by line. Every diff line is either:
  - (a) An intended change from the plan (column rename, format change, AGE/STATUS standardization), explicitly listed in `audit-after.md`'s diff section, OR
  - (b) An expected change due to changed data (timestamps, ages, hostnames).
- [ ] No category-(c) "unexpected regression" lines remain.

### Gate 5 — docs lint

- [ ] `docs/installation.md` and `website/docs/installation.md` produce zero diff when their bodies are compared (per AGENTS.md mirror rule).
- [ ] `grep -rn '\bclm\b' README.md AGENTS.md CONTRIBUTING.md docs/ | grep -v 'historical'` returns zero matches.
- [ ] CHANGELOG.md `BREAKING` section present, complete, and matches the plan §5 BEFORE→AFTER table.

### Gate 6 — integration PR open

- [ ] PR `feat/435-clawctl-ux` → `main` opened with description summarizing all 5 bundles, linking each bundle's sub-issue + PR, and embedding Gate 3's `e2e-validation.md` transcript.
- [ ] Issue #435 referenced via `Closes #435` in the PR body.
- [ ] Review requested per AGENTS.md review-mode rules (`.claude/itx-config.json` `mcp.review_enabled`).

---

## Risk register (carried forward from earlier scaffold)

| # | Risk | Status | Mitigation |
|---|---|---|---|
| R1 | Bundle 4 adds `src/clawrium/core/channels.py` (one core addition vs plan §2 guardrail) | active | New file only, no modifications; documented in Bundle 4 PR. |
| R2 | Top-level CLI registration merge conflicts across bundles | mitigated | Bundle 2 lands complete group skeleton; later bundles fill internals only. Stacked branches further reduce conflict surface. |
| R3 | Discord/Slack prompts present at end of Bundle 3; non-interactive claim not yet true | tracked | Block Bundle 5 docs claim until Bundle 4 extracts them. Codified by `test_configure_no_channel_prompts.py` in Bundle 4. |
| R4 | Template renames leave stale dropin files on existing installs until next `sync` | accepted | CHANGELOG (Bundle 5) lists post-upgrade `sync` as required step. |
| R5 | wolf-i unreachable mid-execution | open | Bundle 1 and Bundle 5 audits both require wolf-i; if unreachable, pause that bundle, do not synthesize. |
| R6 | Stacked branches diverge from `main` as the issue takes time | new | Rebase `feat/435-clawctl-ux` onto `main` weekly; cascade rebase up the bundle stack. Document any conflicts in the stack-head bundle. |
| R7 | Bundle 3's wolf-i integration test (gated by `CLAWCTL_REAL=1`) drifts from real wolf-i state | new | Bundle 3 PR captures wolf-i fixture snapshot; Bundle 5 audit-after regenerates it. |

---

## Appendix A — Original 10-phase decomposition

The 5 bundles above pack the original 10 phases as follows:

| Bundle | Phases |
|---|---|
| Bundle 1 | P0 |
| Bundle 2 | P1 + P2 |
| Bundle 3 | P3 + P4 |
| Bundle 4 | P5 + P6 + P7 |
| Bundle 5 | P8 + P9 + P10 |

The 10-phase dependency graph (preserved for reference):

```
P0 (audit-before) ──► P1 (foundation) ──┬─► P2 (service + meta)
                                        ├─► P3 (host)
                                        ├─► P4 (agent core + lifecycle)
                                        │       │
                                        │       ├─► P5 (Pattern A: provider, integration, skill, mcp)
                                        │       ├─► P6 (Pattern A NEW: channel)
                                        │       └─► P7 (agent secret + memory)
                                        └─► P8 (templates rename + validation)
                                                │
                          (P2..P8 all done) ────┴─► P9 (GUI strings + docs + blog + CHANGELOG)
                                                            │
                                                            └─► P10 (audit-after + regression diff)
```

Stacking sacrifices the P2..P8 parallelism for merge-conflict elimination
and cleaner per-bundle review boundaries.

---

## Execution Scaffolding (prompt log)

### Initial scaffolding — 10-phase parallelizable

**Stage**: scaffolding
**Skill**: /itx:plan-scaffold
**Timestamp**: 2026-05-24T02:54:59Z
**Model**: claude-opus-4-7

```prompt
/itx-plan-scaffold 435
```

**Output**: Drafted a 10-phase multi-phase execution plan with explicit
dependency graph allowing P2..P8 to run in parallel after P1. Each phase
carried entry/exit criteria, dependency list, affected files, complexity
rating. Risk register covered core-guardrail exception, CLI registration
merge contention, prompt-extraction sequencing, audit interactivity.

### Revised scaffolding — 5 stacked bundles, branch-isolated execution

**Stage**: scaffolding
**Skill**: /itx:plan-scaffold
**Timestamp**: 2026-05-24T02:54:59Z
**Model**: claude-opus-4-7

```prompt
write these in a file with specific outcomes to validate. bundle structure is fine.
create the scaffold file first. this is a large task and i dont want the execution to
get derailed in middle. also, all of tehse wil happen in a branch and subtree -> main
wil not be touched adn end to end validation will be done in the branch. so this will
be a stacked branch execution with one bundle layering on top of others till end to
end is done. update plan
```

**Output**: Replaced parallelizable 10-phase plan with **5 stacked bundles
on a long-lived `feat/435-clawctl-ux` integration branch in a git worktree
at `~/workspace/ric03uec/clawrium-issue-435/`**. Each bundle branches off
the previous bundle's tip; PRs target the integration branch, not `main`.
Each bundle now carries an explicit, verifiable **Specific Outcomes to
Validate** checklist (commands that must succeed, files that must exist,
tests that must be added, grep audits that must return zero matches) so
execution can't get fuzzy mid-bundle. Added an **End-to-End Validation
Gate** with six sub-gates (clean rebuild, full test suite, wolf-i live
fleet end-to-end, regression diff, docs lint, integration PR open) that
must all pass before the single integration → main PR opens. `main` is
not touched at any point during execution. Original 10-phase
decomposition preserved as Appendix A.
