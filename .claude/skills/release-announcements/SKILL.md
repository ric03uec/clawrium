---
name: release-announcements
description: Daily prompt for Maurice — draft a release blog post + Discord announcement on every new clawrium release
argument-hint: "[optional: release tag to force, e.g. v26.6.0]"
---

# release-announcements

## What this is

A single prompt sent to Maurice (clawrium's hermes Program Manager agent) once
per day. On every new `ric03uec/clawrium` GitHub release, Maurice drafts a blog
post on the **Blog Pipeline** kanban (Ready lane, assignee `default`) and posts
a short outcome-focused announcement to the `#announcements` Discord channel.

This skill owns the **prompt template** + **content rules** the cron sends to
Maurice. Cron registration itself is out of scope (set up separately).

## Acceptance criteria

For each release published since Maurice's last successful run:

- If `git log <prev_tag>..<tag>` has **zero commits** (re-tag) → no card, no
  Discord post, log `skipped: re-tag`.
- Otherwise:
  - A kanban card exists on Blog Pipeline / Ready / assignee `default`, titled
    `Blog draft: clawrium v<version>`.
  - A Discord message exists in `#announcements` mentioning `v<version>`.
  - The release tag is recorded in Maurice's memory so it isn't reprocessed.
- Maurice replies with one structured line per release:
  `release=<tag> card=<url> discord_msg_id=<id>` (or `skipped: <reason>`).

## Blog content rules — single source of truth

**The blog post content rules (triage, structure, voice, anti-patterns) live in
`skills/hermes/blog-author/SKILL.md` and are reused verbatim here.** That skill
is the canonical writer's bar for clawrium blog posts.

When Maurice drafts the blog body, it follows that skill's:

- **Triage rule** — what qualifies as a user-facing change (new `clawctl`
  command/option/workflow; new agent type, integration, channel, or skill; new
  GUI route or page; behavior change a user would notice on upgrade). Skip
  internal refactors, dependency bumps, test changes, docs-only edits, security
  fixes.
- **Output structure** — required front-matter, body sections (What changed →
  Why → Try it → Links), runnable snippet requirement, ~250–400 words.
- **Hard constraints** — runnability of snippets is non-negotiable; never merge
  own work; never publish (status stays `draft`).
- **Voice** — engineer-to-engineer; no marketing fluff; no first-person
  singular.
- **Anti-patterns** — no lifted paragraphs from release notes; no padding; no
  invented CLI commands or option names.

Differences from `blog-author` for **this** skill:

| Aspect | `blog-author` | `release-announcements` |
|---|---|---|
| Output | One PR per user-visible feature | One kanban card per release |
| Author front-matter | `author: maurice` | `authors: [maurice]` (Docusaurus list form) |
| Cadence | Every 30 min, poll | Daily, cron |
| Side effect | None | Posts Discord announcement same run |

The Docusaurus blog under `website/blog/` uses the list-form `authors:` field
(see existing posts and `website/blog/authors.yml`). Maurice writes the
draft to `website/blog/<YYYY-MM-DD>-v<version>-release.md` and includes the
intended path inside the kanban card body so a human can land it with one
copy.

## Net-new content rules in this skill

### Discord announcement format

Single message in `#announcements`, ≤500 chars, no markdown headers, no
`@here` / `@everyone`:

```
clawrium v<version> is out 🎉

<one sentence on the biggest user-facing change>
<one sentence on the next biggest>
<optional third line if there's a clear third>

Upgrade: uv tool install clawrium@<version>
Full notes: <github release url>
```

Rules:

- Lead with the **outcome**, not the version number. ("Manage agents on your
  Mac mini — clawrium v26.6.0 is out" beats "v26.6.0 released".)
- Max 3 highlights.
- Drop the "Under the hood" section entirely — Discord is the user-facing
  surface. The one exception: a release that **is** a tech-improvement release
  (perf, reliability) — then the tech improvement is the outcome.
- Always include the upgrade command + GitHub release URL.

### Kanban card shape

- **Board**: Blog Pipeline
- **Lane**: Ready
- **Assignee**: `default`
- **Title**: `Blog draft: clawrium v<version>`
- **Body**:
  - Full draft markdown (frontmatter + body)
  - Intended file path: `website/blog/<YYYY-MM-DD>-v<version>-release.md`
  - GitHub release URL
- **Labels**: `release-announcement`, `v<version>`

Maurice checks for an existing card with that title before creating a new one.

## Agent sections

### hermes (active)

**Invocation** (what the cron runs):

```bash
clawctl agent chat maurice "$(cat <<'EOF'
<the prompt template below>
EOF
)"
```

**Prompt template** (verbatim, sent to Maurice):

```
You are Maurice, the Program Manager for the clawrium project. Once per day,
check ric03uec/clawrium for new GitHub releases and produce a blog draft +
Discord announcement for each one.

For each release published since your last successful run:

1. Run: gh release view <tag> --json body,publishedAt,tagName,url
2. Run: git log <prev_tag>..<tag> --oneline
   - If the range contains zero commits, skip this release entirely and reply
     "release=<tag> skipped: re-tag".
3. Apply the content rules from skills/hermes/blog-author/SKILL.md to triage
   the commits into user-facing items vs under-the-hood vs drop.
4. Draft the blog post per that skill's structure rules. Author field uses the
   Docusaurus list form: `authors: [maurice]`. File path:
   website/blog/<YYYY-MM-DD>-v<version>-release.md.
5. Check Blog Pipeline for an existing card titled
   "Blog draft: clawrium v<version>". If one exists, do NOT create a duplicate
   — reply with the existing card URL.
6. Otherwise create a card on Blog Pipeline:
     Lane:     Ready
     Assignee: default
     Title:    "Blog draft: clawrium v<version>"
     Body:     the full draft markdown
               + intended file path
               + GitHub release URL
     Labels:   release-announcement, v<version>
7. Check the last 7 days of messages in the #announcements Discord channel.
   If any message mentions v<version>, do NOT repost — reply with the
   existing message id.
8. Otherwise post a Discord message in #announcements following the Discord
   format in this skill (≤500 chars, outcome-first, max 3 highlights,
   no @here/@everyone, include upgrade command + release URL).
9. Record the release tag in your memory so it is not reprocessed.
10. Reply with one structured line per release:
      release=<tag> card=<url> discord_msg_id=<id>
    or: release=<tag> skipped: <reason>

Configuration you can assume on this agent:
- Blog Pipeline kanban board exists with a `Ready` lane.
- A profile named `default` exists.
- A Discord channel attachment exists; channel name is `announcements`.
- The gh CLI is authenticated for ric03uec/clawrium.

If any assumed configuration is missing, do NOT improvise — reply
"config-error: <what's missing>" and stop. Do not silently swallow failures.

Forbidden:
- Combining multiple releases into one card or message.
- Inventing clawctl commands or option names not present in the source tree.
- Posting Discord messages with @here, @everyone, or any role ping.
- Auto-drafting security fixes — flag them for a human and skip the post.
- Publishing the blog (the draft stays as a kanban card; a human lands it).
```

**Configuration assumed on Maurice**:

- Blog Pipeline kanban board exists with a `Ready` lane.
- Profile `default` exists.
- Discord channel attached; channel name is `announcements`.
- `gh` authenticated for `ric03uec/clawrium`.

**Failure modes Maurice must surface (not swallow)**:

- Board / lane / profile missing → `config-error: <what's missing>`
- Discord channel not resolvable → `config-error: announcements channel`
- `gh` auth failure → `config-error: gh auth`

### openclaw (placeholder)

**Status**: not yet implemented.

**When implemented**: an equivalent prompt template adapted to openclaw's task
surface (e.g. GitHub-issue fallback if openclaw has no kanban primitive yet)
and openclaw's Discord attachment. The blog content rules and Discord format
above apply unchanged.

**Until then**: do **not** attach this skill to openclaw agents. If invoked
on an openclaw agent, the prompt above will fail at step 6 (no kanban) and
exit with `config-error: kanban board not available on openclaw`.

## Mirror requirement

This skill exists at two paths and they must stay byte-identical:

- `.claude/skills/release-announcements/SKILL.md`
- `.opencode/skills/release-announcements/SKILL.md`

Any edit to one must be mirrored to the other in the same commit. See the
"Mirrored Developer Skills" section in `AGENTS.md`.

## Anti-patterns

- Do **not** duplicate the blog content rules here. They live in
  `skills/hermes/blog-author/SKILL.md`; this skill references them.
- Do **not** wire the cron from inside this skill — cron registration is a
  separate concern, kept out so the skill remains a pure content/prompt
  contract.
- Do **not** widen Maurice's permissions on failure (e.g. "if the kanban
  board doesn't exist, create it"). Fail fast with `config-error:` so the
  operator notices a drift in Maurice's environment.
- Do **not** auto-publish the blog post. The kanban card is the editorial
  gate; a human lands the file under `website/blog/`.
