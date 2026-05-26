# Implementation Plan (Revised) — #431

## Why this plan supersedes the original

The original #431 proposal added two optional fields (`GIT_USER_NAME`,
`GIT_USER_EMAIL`) to the **github** integration and wrote them via inline
`git config --global` Ansible commands. Two problems with that shape:

1. **Couples git identity to a forge.** Agents using gitlab, self-hosted
   git, or no forge at all still need a commit identity. Sticking the
   fields on `github` strands them.
2. **Inline `git config` commands are not reviewable.** The agent's
   `~/.gitconfig` becomes a side-effect of N commands; you cannot diff
   the file, version it, or extend it with non-identity keys (default
   branch, pull strategy, editor) without piling on more inline commands.

Issue #531 already proposes the correct shape: a **standalone `git`
integration** rendered from a Jinja `gitconfig.j2` template. This plan
adopts #531 as the implementation of #431 and recommends closing #431
as superseded once #531 ships.

## Token boundary (confirmed)

`gitconfig.j2` never contains a token. The boundary stays:

| Where | What lives there |
|---|---|
| `10-<claw>-env.conf` (systemd drop-in, mode 0600) | `GITHUB_TOKEN` env var for the process |
| `gh` auth store (`~/.config/gh/hosts.yml` per agent user) | OAuth credential, set by `gh auth login --with-token` |
| `~/.gitconfig` (template-rendered, this plan) | `[user]`, `[init]`, `[pull]`, `[core]` only |
| `~/.gitconfig` (`gh auth setup-git` writes this on top) | `credential.helper = !gh auth git-credential` — a *pointer*, not a token |

When git needs to push, it invokes `gh auth git-credential`, which reads
`GITHUB_TOKEN` from env. The token is never serialized to a config file.

## Overview

Implement #531's standalone `git` integration with five fields and sane
defaults. All three claws (zeroclaw, hermes, openclaw) render
`gitconfig.j2` during configure for each assigned `git` integration.

## Schema — `src/clawrium/core/integrations.py`

Add a `git` entry to `INTEGRATION_TYPES`:

| Key | Required | Default at prompt | Rendered as |
|---|---|---|---|
| `GIT_USER_NAME`           | yes | local `git config --global user.name`  | `[user] name`           |
| `GIT_USER_EMAIL`          | yes | local `git config --global user.email` | `[user] email`          |
| `GIT_INIT_DEFAULT_BRANCH` | no  | `main`                                 | `[init] defaultBranch`  |
| `GIT_PULL_REBASE`         | no  | `false`                                | `[pull] rebase`         |
| `GIT_CORE_EDITOR`         | no  | `vim`                                  | `[core] editor`         |

Identity is required because an identityless `~/.gitconfig` is the foot-gun
we are closing. Other fields default at template-render time, so the operator
can accept blanks at prompt time and still get a working file.

Storage rides the existing per-integration credentials path
(`secrets.json`). Reusing the credential store avoids inventing a parallel
"config fields" mechanism. The reuse is acknowledged as a name-fit
compromise (`GIT_USER_NAME` is not strictly a secret) and is consistent
with how #431 originally proposed storing the same data.

## CLI — `src/clawrium/cli/integration.py`

`clm integration add --type git <name>` walks the five fields in the
table order. For each prompt:

- If the field has a function-derived default (the two identity fields),
  shell out: `subprocess.run(['git', 'config', '--global', '<key>'],
  capture_output=True)`. On non-zero or `FileNotFoundError`, default to `""`.
- Static defaults (`main` / `false` / `vim`) pre-populate directly.
- Operator hits Enter to accept or types to override.
- For required fields, an empty submission re-prompts.

**Update verb.** Confirm during implementation whether the CLI supports
updating fields on an existing integration without `remove + re-add`. If
it doesn't, add an update path in this phase — otherwise live verification
in Phase 3 has no way to backfill the existing `clawrium-d01-github`
integration without losing its credentials.

## Template — `src/clawrium/platform/templates/gitconfig.j2`

Single shared template (the rendering is identical across claws —
co-locating per-claw would be three copies of the same file).

```ini
[user]
    name = {{ git.user_name }}
    email = {{ git.user_email }}

[init]
    defaultBranch = {{ git.init_default_branch | default('main') }}

[pull]
    rebase = {{ git.pull_rebase | default('false') }}

[core]
    editor = {{ git.core_editor | default('vim') }}
```

Last-write-wins if an operator assigns multiple `git` integrations to one
agent — same semantics as the existing `GITHUB_TOKEN` drop-in. Document
it; don't error on it.

## Playbook task — one per claw

Three files, identical task body, positioned **after** the `gh auth
setup-git` task so the file `gh auth setup-git` mutates is the one this
template produced (otherwise the credential.helper line gets overwritten
by the template run):

- `src/clawrium/platform/registry/zeroclaw/playbooks/configure.yaml`
- `src/clawrium/platform/registry/hermes/playbooks/configure.yaml`
- `src/clawrium/platform/registry/openclaw/playbooks/configure.yaml`

```yaml
- name: Render ~/.gitconfig for each git integration
  become_user: "{{ agent_name }}"
  ansible.builtin.template:
    src: gitconfig.j2
    dest: "/home/{{ agent_name }}/.gitconfig"
    owner: "{{ agent_name }}"
    group: "{{ agent_name }}"
    mode: "0644"
  loop: "{{ integrations | dict2items | selectattr('value.type', 'equalto', 'git') | list }}"
  loop_control:
    label: "{{ item.key }}"
  vars:
    git:
      user_name:            "{{ item.value.GIT_USER_NAME | default('') }}"
      user_email:           "{{ item.value.GIT_USER_EMAIL | default('') }}"
      init_default_branch:  "{{ item.value.GIT_INIT_DEFAULT_BRANCH | default('main') }}"
      pull_rebase:          "{{ item.value.GIT_PULL_REBASE | default('false') }}"
      core_editor:          "{{ item.value.GIT_CORE_EDITOR | default('vim') }}"
```

**Ordering pin** — registry tests must assert the render task is positioned
after `Configure git credential helper via gh auth setup-git`. Reverse
order silently drops the credential.helper line.

**No-op when no `git` integration is assigned** — the `selectattr` filter
returns an empty list and the loop becomes a no-op. Existing agents
unchanged.

## Test strategy

**`tests/test_core_integrations.py`**
- `test_git_integration_exposes_five_fields_with_required_flags`
- `test_git_integration_required_fields_are_only_user_name_and_email`
- `test_other_integration_types_do_not_expose_git_fields`
- `test_legacy_integrations_without_git_type_load_cleanly`

**`tests/test_cli_integration.py`**
- `test_git_add_prefills_identity_from_local_git_config` — patch
  `subprocess.run` to return canned name/email.
- `test_git_add_handles_missing_local_git_config` — `subprocess.run` returns
  empty / non-zero; required prompts re-prompt; static defaults still applied.
- `test_git_add_applies_static_defaults_for_optional_fields` — assert
  `main`/`false`/`vim` show as prompt defaults.
- `test_git_add_operator_override_persists` — operator types non-default
  values; assert they land in the integration record.

**Playbook structural tests** — extend per claw:
- `tests/test_registry_zeroclaw.py`
- `tests/test_registry_hermes.py` (create if absent)
- `tests/test_registry_openclaw.py` (create if absent)

Each asserts:
- Render task present, gated on `type == 'git'`, runs as
  `become_user: "{{ agent_name }}"`.
- Positioned **after** the `gh auth setup-git` task.
- `dest`, `owner`, `group`, `mode` match the spec above.

**Template render test** — new `tests/test_gitconfig_template.py`:
- `test_renders_full_input` — all five fields set; assert exact file body.
- `test_renders_identity_only_with_defaults` — only the two required fields
  set; assert `main`/`false`/`vim` come through.

## Phasing

### Phase 1 — Schema + CLI prompt + template (no playbook side effects)

**Files**
- `src/clawrium/core/integrations.py` — add `git` entry.
- `src/clawrium/cli/integration.py` — add prompt flow with local-git defaults.
- `src/clawrium/platform/templates/gitconfig.j2` — new shared template.

**Tests** — all `tests/test_core_integrations.py`,
`tests/test_cli_integration.py`, and `tests/test_gitconfig_template.py`
cases from above.

**Exit criteria**
- `make test` green.
- `clm integration add --type git foo` walks the five prompts with defaults.
- Rendering `gitconfig.j2` standalone produces the expected file.
- Zero behavioural change on any agent on disk.

### Phase 2 — Per-claw playbook render task

**Files** — three `configure.yaml`s (one per claw), one new task each.

**Tests** — three `tests/test_registry_<claw>.py` cases.

**Exit criteria per claw**
- `make test` green.
- Live: `printf '9\n' | clm agent configure clawrium-d01 --stage providers`,
  then `sudo cat /home/clawrium-d01/.gitconfig` matches the integration's fields.

### Phase 3 — Live verification + close #431

1. Backfill the existing `clawrium-d01-github` integration's identity into a
   new `git`-type integration (e.g. `clawrium-d01-git`) via the new CLI prompts.
2. Attach the `git` integration to `clawrium-d01`.
3. Reinstall clm: `uv tool install --force --reinstall .`
4. `clm agent configure clawrium-d01 --stage providers`.
5. `sudo cat /home/clawrium-d01/.gitconfig` — verify all five keys, written by
   ansible (not by the earlier manual edit).
6. Optional: fresh hermes / openclaw agent to confirm cross-claw parity.
7. Close #431 as superseded by #531. Reference this plan in the closing
   comment so the linkage is obvious in history.

**Exit criteria**
- Acceptance criteria boxes on #531 all checked.
- `make test` and `make lint` green.
- #431 closed with a forward pointer to the merged #531 PR.

## Subtasks

Recommend creating three subtask issues under #531 (not #431, since #431
is being closed):

- `[Parent #531] Phase 1 — git integration schema, CLI prompts, gitconfig.j2 template`
- `[Parent #531] Phase 2 — Render gitconfig.j2 in zeroclaw / hermes / openclaw configure.yaml`
- `[Parent #531] Phase 3 — Live verify on clawrium-d01 and close #431`

## Risks & open questions

1. **Update verb on `clm integration`.** If absent, Phase 1 must add it —
   otherwise Phase 3's backfill requires `remove + re-add`, which destroys
   credentials. Investigate during Phase 1.
2. **Field naming.** `GIT_USER_NAME` etc. use the shouty-case credential
   convention even though these aren't credentials. Trade-off accepted:
   one storage surface (`secrets.json`) is simpler than two.
3. **Empty-value semantics.** If the operator clears a previously-set field
   and re-configures, this plan does **not** `git config --unset`. Empty
   value = template renders the default. Explicit unset is a follow-up.
4. **Per-claw identity divergence.** Multiple `git` integrations attached
   to one agent → last-write-wins on `~/.gitconfig`. For true per-agent
   identity, attach distinct `git` integrations to distinct agents. Same
   constraint applies to #431's original design.
5. **Hermes task ordering density.** Hermes' `configure.yaml` interleaves
   atlassian MCP bootstrap. Pin the position in the registry test —
   directly after `gh auth setup-git`, before atlassian.

## Out of scope (unchanged from #531)

- GPG / SSH commit signing.
- Per-claw identity divergence within a single integration.
- Migrating existing manual `~/.gitconfig` writes into integration records.
- `credential.helper` / token-based HTTPS push wiring (lives with #432).
- Touching any `*-env.conf.j2`.

## Prompt Log

## Planning (revised)

**Stage**: plan
**Skill**: /itx:plan-create
**Timestamp**: 2026-05-25T00:00:00Z
**Model**: claude-opus-4-7

```prompt
431. the existing issue suggets moving thse configuration as part of git config command. but i want these to be part of gitconfig file. with sane defaults. look at linked issue as well. give me updated plan
```

**Output**: Revised plan that adopts #531's standalone `git` integration + `gitconfig.j2` template approach as the implementation of #431, and recommends closing #431 as superseded once #531 ships. Confirms token boundary: no token in any rendered config file.
