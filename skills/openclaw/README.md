# skills/openclaw/

Native openclaw skills. Files placed here are installable **only** onto
agents of type `openclaw`. The CLI rejects cross-claw installs with
`IncompatibleSkillRegistry` (Phase 2).

Layout:

```
skills/openclaw/<name>/
└── SKILL.md   # frontmatter validated against _schema/native/openclaw.schema.json
```

A cross-agent skill belongs in `skills/clawrium/` instead — see the
top-level [`skills/README.md`](../README.md). No native openclaw skills
ship in this initial cut; this directory is a registered registry so that
`clawctl skill list --registry openclaw` returns an empty list rather than a
"registry not found" error.
