---
description: Author a new local-source clawrium skill (#411)
---

# /skill-create

Use this command to draft a new **local-source** clawrium skill and
install it via `clawctl skill add`.

## Instructions

1. Ask the user for the four required inputs:
   - **name** — lowercase, matches `^[a-z0-9][a-z0-9_-]*$`, globally
     unique across the unified catalog (cannot collide with any
     `vetted/<name>` or existing `local/<name>`). Name is immutable
     after creation.
   - **description** — one short line; appears in `clawctl skill list`
     and the GUI catalog.
   - **purpose** — 2-3 sentences on what the skill does and when it
     should be invoked. Used to draft the body.
   - **trigger** — when should the agent invoke this skill?

2. Optionally collect:
   - **version** (default `0.1.0`)
   - **author** (default: the git user)
   - **tags** (comma-separated)

3. Draft the SKILL.md body in agentskills.io format. Frontmatter must
   include `name` and `description`. The body is markdown that the
   agent reads at runtime — write it as a short procedure (numbered
   steps, code examples where helpful).

4. Write the draft to a temp file (e.g. `/tmp/skill-<name>.md`) with
   YAML frontmatter at the top:

   ```markdown
   ---
   name: <name>
   description: <one-line>
   version: 0.1.0
   author: <author>
   ---

   # <Title>

   <body>
   ```

5. Install it with:

   ```bash
   clawctl skill add local/<name> --body-file /tmp/skill-<name>.md
   ```

   (The `--body-file` flag accepts both a body-only markdown file and
   a full SKILL.md with frontmatter. The CLI re-emits `name` to match
   the slug.)

6. Verify:

   ```bash
   clawctl skill list | grep local/<name>
   clawctl skill show local/<name>
   ```

7. Attach to a hermes agent (the only claw type currently supported):

   ```bash
   clawctl agent skill attach local/<name> --agent <hermes-agent>
   ```

## Notes

- `openclaw` and `zeroclaw` agents will reject attach with
  `ClawNotSupported` until follow-up issues re-enable them.
- The `name` is immutable. To rename, delete (`clawctl skill remove
  local/<name>`) and create the new one.
- Vetted skills live at `skills/vetted/<name>/SKILL.md` in the repo
  and require a PR. This command only handles local skills.
