# Clawrium Skills Catalog

This directory is the **single source of truth** for skills installable via
`clawctl` onto clawrium-managed agents. Skills are organized into four
**registries** (namespaces). The path layout is hard-wired into
`src/clawrium/core/skills.py` and validated in CI.

```
skills/
├── _schema/
│   ├── clawrium.schema.json            # cross-agent normalized shape
│   └── native/
│       ├── openclaw.schema.json        # openclaw SKILL.md frontmatter
│       ├── hermes.schema.json          # hermes SKILL.md frontmatter
│       └── zeroclaw.schema.json        # zeroclaw SKILL.md frontmatter
├── clawrium/<name>/                    # normalized, cross-agent
│   ├── _meta.yaml                      # required, validated against clawrium.schema.json
│   ├── SKILL.md                        # canonical content (rendered per claw on apply)
│   └── README.md                       # optional, human-readable docs
├── openclaw/<name>/                    # native, openclaw-only
│   └── SKILL.md                        # frontmatter validated against native/openclaw.schema.json
├── hermes/<name>/                      # native, hermes-only
│   └── SKILL.md                        # frontmatter validated against native/hermes.schema.json
└── zeroclaw/<name>/                    # native, zeroclaw-only
    └── SKILL.md                        # frontmatter validated against native/zeroclaw.schema.json
```

## Namespace rules

| Registry    | Schema     | Install target            | Notes                                              |
|-------------|------------|---------------------------|----------------------------------------------------|
| `clawrium`  | clawrium   | any agent type            | normalized superset; materialized per claw on apply |
| `openclaw`  | native     | only `openclaw` agents    | raw openclaw SKILL.md, dropped under `~/.openclaw/skills/` |
| `hermes`    | native     | only `hermes` agents      | raw hermes SKILL.md, dropped under `~/.hermes/skills/clawrium/` |
| `zeroclaw`  | native     | only `zeroclaw` agents    | staged + installed via `zeroclaw skills install` (audit gate) |

## Skill references

Skills are referenced as `<registry>/<name>` everywhere — CLI args, GUI URLs,
desired-state files. Bare names (e.g. `tdd`) are rejected with
`MissingRegistryPrefix` and a hint that includes the matching registries.

Non-registry sources (URLs, absolute paths, tarballs) are rejected at the
`parse_skill_ref` chokepoint with `ExternalSourceBlocked`. The only install
source for `clawctl` is this in-repo tree.

## Slug rules

- `<name>` MUST match `^[a-z0-9][a-z0-9_-]*$` (kebab-case, no leading
  hyphen/underscore).
- For `clawrium/<name>`, `_meta.yaml`'s `name:` field MUST equal `<name>`
  (the directory name). The CLI enforces this so that zeroclaw's source-
  dirname semantics (see `.itx/364/02_PHASE0_FINDINGS.md`) stay consistent
  with the registry slug.

## Adding a new skill

1. Pick the right registry.
   - Cross-agent? Use `clawrium/`.
   - Native to one claw and uses claw-specific frontmatter fields? Use that
     claw's namespace.
2. Create `skills/<registry>/<name>/SKILL.md` (and `_meta.yaml` for
   `clawrium/`).
3. Run `clawctl skill show <registry>/<name>` to confirm the catalog loader
   accepts it.
4. CI runs dual-schema validation on every PR; a clawrium-shaped file
   placed under a native registry (or vice versa) will fail the build.

See `docs/skills/authoring-clawrium.md` and
`docs/skills/authoring-native.md` for full authoring guides (Phase 6).
