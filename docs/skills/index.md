# Skills Catalog

<!--
  Repo-rooted docs live in docs/skills/. The user-facing site mirror
  lives at website/docs/skills/ and is a condensed variant: the two
  trees are kept semantically in sync but are not structurally
  identical (this file → intro.md; authoring-clawrium.md +
  authoring-native.md → authoring.md). Update both when changing
  catalog rules.
-->

Clawrium ships a curated catalog of **skills** that any agent in your
fleet can copy into local state and sync to its host. A skill is a directory of
behaviour-shaping prompts and metadata that the underlying claw
discovers at runtime — Test-Driven Development discipline, code-review
guardrails, security-audit playbooks, and so on.

Bundled catalog skills live in the in-repo `skills/` tree. Operators can
also add user-overlay catalog entries under
`~/.config/clawrium/skills/<registry>/<name>/` with `clawctl skill add`.
Both sources use the same registry names and schema validation; the user
overlay wins if it defines the same `<registry>/<name>` as the bundled
catalog.

## Quick start

```bash
# Browse the catalog
clawctl skill registry get

# Inspect a skill before installing
clawctl skill registry describe clawrium/tdd

# Copy the template into an agent-local skill
clawctl agent skill add my-agent --from-template clawrium/tdd

# Apply local skill state to the host
clawctl agent sync my-agent

# List skills installed on an agent
clawctl agent skill list my-agent

# Remove a skill
clawctl agent skill remove my-agent tdd

# Add a user-overlay catalog entry
clawctl skill add ./my-hermes-skill --registry hermes
```

The GUI mirrors the same surface under `Agents → <agent> → Skills`
and a top-level `Skills` catalog page.

## Registries

The catalog is split into four **registries** (namespaces). The split
determines which agents can install a given skill and which JSON schema
its descriptor is validated against.

| Registry   | Install target          | Schema                            |
|------------|-------------------------|-----------------------------------|
| `clawrium` | any agent type          | `_schema/clawrium.schema.json`    |
| `openclaw` | only `openclaw` agents  | `_schema/native/openclaw.schema.json` |
| `hermes`   | only `hermes` agents    | `_schema/native/hermes.schema.json`   |
| `zeroclaw` | only `zeroclaw` agents  | `_schema/native/zeroclaw.schema.json` |

Catalog templates are referenced as `<registry>/<name>` when browsing or
copying from the catalog. Once a template is added to an agent, it is an
agent-local skill named by its bare slug (`tdd`). The local desired-state
file at `~/.config/clawrium/agents/<agent>/skills.json` stores only bare
agent-local names, not registry refs.

### When to use `clawrium/`

Use the `clawrium/` registry when the skill is behaviour you want
available on **every** kind of claw. The normalized `_meta.yaml` shape
is materialized into each native frontmatter format at `clawctl agent
skill add` time — a single source template becomes an openclaw-shaped
local SKILL.md for an openclaw agent, hermes-shaped for a hermes agent,
and zeroclaw-shaped for a zeroclaw agent. `clawctl agent sync` later
copies that already-native local file to the host unchanged.

### When to use a native registry

Use `openclaw/`, `hermes/`, or `zeroclaw/` when the skill depends on
that claw's specific frontmatter fields (e.g. hermes-only `metadata`
keys, openclaw allowed-tools lists). Native skills are installable
**only** on agents of the matching type. Attempting to install a
`hermes/<name>` skill on an openclaw agent fails with
`IncompatibleSkillRegistry`.

## Agent-Local Skills

Agent-local skills live on the control machine under:

```text
~/.config/clawrium/agents/<agent>/skills/<name>/SKILL.md
~/.config/clawrium/agents/<agent>/skills.json
```

`skills.json` is a flat list of local names, for example:

```json
{"skills": ["tdd", "incident-review"]}
```

Registry refs such as `"clawrium/tdd"` are not valid desired state. To
recover an old state file, remove the registry ref and re-add the skill
from its template:

```bash
clawctl agent skill add <agent> --from-template clawrium/tdd
clawctl agent sync <agent>
```

See [Local agent skills](local.md) for path installs, editing, sync
semantics, and the no-collision rule.

## Authoring

| Guide | Use when |
|-------|----------|
| [Authoring clawrium skills](authoring-clawrium.md) | Cross-agent skill — works on every claw |
| [Authoring native skills](authoring-native.md)     | Skill specific to one claw's frontmatter |

Every PR that touches `skills/` runs `scripts/validate_skills.py` in CI
([skills-validate.yml](https://github.com/ric03uec/clawrium/blob/main/.github/workflows/skills-validate.yml))
to catch:

- Slug-rule violations (path-traversal guard).
- Symlinks inside the catalog.
- Schema mismatches (a clawrium `_meta.yaml` mis-placed under a native
  registry, or clawrium-only frontmatter keys in a native SKILL.md).
- Missing required fields on `_meta.yaml` or SKILL.md frontmatter.
- The clawrium "directory name == `_meta.yaml.name`" invariant
  (required for zeroclaw's source-dirname install/remove semantics —
  see `.itx/364/02_PHASE0_FINDINGS.md`).

Run the same checks locally before pushing:

```bash
python scripts/validate_skills.py
```

## On-host materialization

| Claw     | Install location                              | Mechanism                                  |
|----------|-----------------------------------------------|--------------------------------------------|
| openclaw | `~/.openclaw/skills/<name>/SKILL.md`          | file copy (auto-scan)                      |
| hermes   | `~/.hermes/skills/clawrium/<name>/SKILL.md`   | file copy (auto-scan)                      |
| zeroclaw | `~/.zeroclaw/workspace/skills/<name>/`        | staged + `zeroclaw skills install` (audit) |

**The `~` above refers to the agent unix user's home**, not the
operator's home on the control machine. Each agent installed via
`clawctl agent create` runs as its own dedicated user named after the
agent (e.g. `tdd-hermes` runs as user `tdd-hermes`, with files under
`/home/tdd-hermes/`). To SSH-verify after a CLI install, switch users
on the remote host:

```bash
# As the management user (typically xclm), drop into the agent user
sudo -u tdd-hermes ls /home/tdd-hermes/.hermes/skills/clawrium/tdd/
```

`clawctl agent sync <agent>` is the recovery for drift. It reads the
local desired-state file at
`~/.config/clawrium/agents/<agent>/skills.json`, stages each listed
agent-local `SKILL.md` byte-for-byte, and applies that state to the host.

## Ownership boundaries

Pruning never touches user-authored or upstream-bundled skills. Each
claw uses a different marker so a future apply can distinguish
clawrium-managed dirs from anything else:

| Claw     | Marker                                                                                  |
|----------|-----------------------------------------------------------------------------------------|
| openclaw | `.clawrium-managed` sentinel file inside each clawrium-installed skill dir              |
| hermes   | Implicit — clawrium skills live under the dedicated `~/.hermes/skills/clawrium/` subdir |
| zeroclaw | `~/.zeroclaw/.clawrium-managed-skills` (newline-separated slugs, outside `skills/`)     |

If you see a clawrium-installed skill that the prune logic is failing
to recognize, check that its marker is intact.

## Troubleshooting

### `clawctl agent skill add` succeeds but the host file is missing

`clawctl agent skill add` only writes the control-plane copy under
`~/.config/clawrium/agents/<agent>/skills/<name>/`. Run
`clawctl agent sync <agent>` to push that local state to the host.

### `clawctl agent sync` reports success but the file isn't where I expect

The `~` in the on-host paths is the **agent user's** home, not yours.
A common source of confusion when verifying via SSH as the management
user (`xclm` by default):

```bash
# Wrong — checking your own home (or the management user's home)
ssh wolf-i 'ls ~/.hermes/skills/clawrium/tdd/'

# Right — switch to the agent user
ssh wolf-i 'sudo -u tdd-hermes ls /home/tdd-hermes/.hermes/skills/clawrium/tdd/'
```

### `clawctl agent delete` doesn't clean up the local skill state

Known limitation: `~/.config/clawrium/agents/<name>/skills.json` is
left behind when you `clawctl agent delete <name>`. If you re-install
under the same name later, the leftover state is benign (an empty
`{"skills": []}` array), but clean it explicitly if you want a clean
slate:

```bash
rm -rf ~/.config/clawrium/agents/<name>
```

### Local end-to-end smoke test

After making a change to a `skills/clawrium/<name>/` or per-claw
playbook, exercise the full round-trip against a real agent before
opening a PR:

```bash
# 1. Add from a template — should create the local control-plane copy
clawctl agent skill add <agent> --from-template clawrium/<name>

# 2. List — should show it
clawctl agent skill list <agent>

# 3. Sync — should push the local skill to the host
clawctl agent sync <agent>

# 4. Verify on host (substitute the agent's unix user)
ssh <host> "sudo -u <agent-user> ls -la /home/<agent-user>/<claw-skill-path>"

# 5. Duplicate add — should fail and tell you to remove/rename first
clawctl agent skill add <agent> --from-template clawrium/<name>

# 6. Drift recovery — delete on host, sync reconverges
ssh <host> "sudo -u <agent-user> rm -rf /home/<agent-user>/<claw-skill-path>"
clawctl agent sync <agent>

# 7. Remove locally, then sync the removal
clawctl agent skill remove <agent> <name>
clawctl agent sync <agent>
```

### Local validator exit code

`scripts/validate_skills.py` exits **0 on success, 1 on validation
failure**. When checking the exit code in a script, do not pipe stdout
through `tail` / `head` — those overwrite `$?` with the pipe element's
exit. Use:

```bash
python scripts/validate_skills.py; echo "exit=$?"
# or
python scripts/validate_skills.py > /tmp/out.log; echo "exit=$?"
```
