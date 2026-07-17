# skills/hermes/

Native hermes skills. Files placed here are installable **only** onto
agents of type `hermes`. The CLI rejects cross-claw installs with
`IncompatibleSkillRegistry` (Phase 2).

Layout:

```
skills/hermes/<name>/
└── SKILL.md   # frontmatter validated against _schema/native/hermes.schema.json
```

A cross-agent skill belongs in `skills/clawrium/` instead — see the
top-level [`skills/README.md`](../README.md). No native hermes skills ship
in this initial cut; this directory is a registered registry so that
`clawctl skill list --registry hermes` returns an empty list rather than a
"registry not found" error.
