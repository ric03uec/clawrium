---
name: clawrium-release-announcements
description: Daily — draft a release blog post on Blog Pipeline kanban and post a Discord announcement on every new clawrium GitHub release
version: 0.1.0
author: clawrium
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [release, blog, discord, automation, clawrium]
    related_skills: [blog-author]
---

# clawrium-release-announcements

Once per day, check `ric03uec/clawrium` on GitHub for new releases. For each
release that has not yet been processed, draft a release blog post as a card
on the **Blog Pipeline** kanban (Ready lane, assignee `default`) and post a
short outcome-focused announcement to the `#announcements` Discord channel.
Skip releases whose tag range contains zero commits (re-tags).

## When to Use

- Triggered by a daily cron that sends a "check for new clawrium releases"
  request to the agent.
- Triggered ad-hoc by an operator request such as
  "check `ric03uec/clawrium` for new releases" or "produce a release
  announcement for `v<version>`".

Do **not** run this skill more than once per release tag — the procedure is
idempotent (it re-queries kanban and Discord for existing artifacts before
writing), but the intent is one announcement per release.

## Quick Reference

| Phase     | Action                                                                                  |
|-----------|-----------------------------------------------------------------------------------------|
| Discover  | `gh release list --repo ric03uec/clawrium --limit 10`; filter unprocessed tags          |
| Triage    | `git log <prev_tag>..<tag>` — skip if zero commits; classify the rest                   |
| Draft     | Write blog markdown per `skills/hermes/blog-author/SKILL.md` rules                      |
| Publish   | Kanban card on Blog Pipeline / Ready / `default` + Discord post in `#announcements`     |
| Record    | Persist processed tag in agent memory so it is not reprocessed                          |

## Procedure

For each release published since the last successful run of this skill:

1. **Fetch the release.**

   ```bash
   gh release view <tag> --json body,publishedAt,tagName,url
   ```

2. **Compute the commit range.**

   ```bash
   git log <prev_tag>..<tag> --oneline
   ```

   If the range contains zero commits (a re-tag of an already-released
   commit), skip this release entirely and reply:

   ```
   release=<tag> skipped: re-tag
   ```

3. **Triage the commits.**

   Apply the triage rules from `skills/hermes/blog-author/SKILL.md` to
   classify each commit as user-facing, under-the-hood, or drop.

4. **Draft the blog post.**

   Follow the **output structure**, **voice**, and **anti-patterns** sections
   of `skills/hermes/blog-author/SKILL.md`. The post body MUST use that
   skill's required structure (What changed → Why → Try it → Links) and word
   budget (~250–400 words).

   Use the Docusaurus list-form authors field for this repo:

   ```yaml
   ---
   slug: v<version>-release
   title: "What's new in clawrium v<version>"
   authors: [maurice]
   tags: [release-notes]
   date: <YYYY-MM-DD from release publishedAt>
   ---
   ```

   Intended file path:
   `website/blog/<YYYY-MM-DD>-v<version>-release.md`. Maurice does NOT land
   the file directly — the kanban card carries the draft and the intended
   path so a human reviewer commits it.

5. **Check for an existing kanban card.**

   Search Blog Pipeline for a card titled exactly
   `Blog draft: clawrium v<version>`. If one exists, do **not** create a
   duplicate — reply with the existing card URL and continue to step 7.

6. **Create the kanban card.**

   | Field    | Value                                                       |
   |----------|-------------------------------------------------------------|
   | Board    | Blog Pipeline                                               |
   | Lane     | Ready                                                       |
   | Assignee | `default`                                                   |
   | Title    | `Blog draft: clawrium v<version>`                           |
   | Body     | full draft markdown + intended file path + release URL      |
   | Labels   | `release-announcement`, `v<version>`                        |

7. **Check Discord for a recent announcement.**

   Read the last 7 days of messages in the `#announcements` channel. If any
   message mentions `v<version>`, do **not** repost — reply with the
   existing message id and continue to step 9.

8. **Post the Discord announcement.**

   Single message in `#announcements`, ≤500 characters, no markdown headers,
   no `@here` / `@everyone`:

   ```
   clawrium v<version> is out 🎉

   <one sentence on the biggest user-facing change>
   <one sentence on the next biggest>
   <optional third line if there is a clear third>

   Upgrade: uv tool install clawrium@<version>
   Full notes: <github release url>
   ```

   Rules:

   - Lead with the **outcome**, not the version number.
   - Maximum 3 highlights.
   - Drop the "Under the hood" section entirely — Discord is the
     user-facing surface. The only exception is a release that **is** a
     tech-improvement release (perf, reliability), in which case the tech
     improvement IS the outcome.
   - Always include the upgrade command and the GitHub release URL.

9. **Record the tag.**

   Persist `<tag>` in agent memory under the key
   `clawrium-release-announcements:processed` so this release is not
   reprocessed on the next run.

10. **Reply.**

    One structured line per release processed:

    ```
    release=<tag> card=<url> discord_msg_id=<id>
    ```

    or, if skipped:

    ```
    release=<tag> skipped: <reason>
    ```

## Content rules

### Blog body — single source of truth

The blog post's body content rules (**triage**, **output structure**,
**hard constraints**, **voice**, **anti-patterns**) live in
`skills/hermes/blog-author/SKILL.md` and apply unchanged here. Do NOT
duplicate those rules in this skill.

The only differences specific to this skill:

| Aspect              | `blog-author`             | this skill                                              |
|---------------------|---------------------------|---------------------------------------------------------|
| Output surface      | One PR per feature        | One kanban card per release                             |
| Author front-matter | `author: maurice`         | `authors: [maurice]` (Docusaurus list form)             |
| Cadence             | Every 30 min, poll        | Daily                                                   |
| Side effect         | None                      | Posts a Discord announcement in the same run            |

### Discord format

Already specified inline in step 8 of the Procedure. Treat that block as the
canonical Discord template.

### Kanban card shape

Already specified inline in step 6 of the Procedure. Treat that block as the
canonical kanban card template.

## Configuration assumed

The skill expects the following to be configured on the agent. If any are
missing, **fail fast** — do not improvise.

| Requirement                                            | Failure reply                                |
|--------------------------------------------------------|----------------------------------------------|
| `gh` CLI installed and authenticated for `ric03uec/clawrium` | `config-error: gh auth`                |
| Blog Pipeline kanban board exists                      | `config-error: Blog Pipeline board missing`  |
| `Ready` lane exists on Blog Pipeline                   | `config-error: Ready lane missing`           |
| Profile named `default` exists                         | `config-error: default profile missing`      |
| Discord channel attachment named `announcements`       | `config-error: announcements channel missing`|

On any `config-error:`, stop the run for that release; do not partially
publish.

## openclaw (placeholder)

Status: not yet implemented.

When implemented, this skill will be ported to openclaw with the equivalent
task surface (e.g. a GitHub-issue fallback if openclaw has no kanban
primitive) and openclaw's Discord attachment. The blog body rules and
Discord format above apply unchanged.

Until then, do **not** attach this skill to openclaw agents.

## Pitfalls

- Combining multiple releases into a single kanban card or Discord message.
- Inventing `clawctl` commands or option names that are not present in the
  source tree (`src/clawrium/cli/`).
- Discord posts containing `@here`, `@everyone`, or any role ping.
- Auto-drafting a release announcement for a security fix — flag for a
  human and skip the announcement entirely.
- Publishing the blog post directly (landing the file under `website/blog/`
  yourself). The kanban card is the editorial gate; a human commits the
  file.
- Silently swallowing missing configuration. Always reply
  `config-error: <what>` and stop.

## Verification

For each release processed in a run, all of the following MUST be true:

- A kanban card titled `Blog draft: clawrium v<version>` exists on
  Blog Pipeline in the `Ready` lane, assignee `default`, with the
  `release-announcement` and `v<version>` labels.
- A Discord message in `#announcements` mentions `v<version>` and contains
  the upgrade command and the GitHub release URL.
- The tag `<tag>` is present in agent memory under
  `clawrium-release-announcements:processed`.

For releases skipped because of zero commits:

- No kanban card exists for that version.
- No Discord message references that version.
- The reply line is `release=<tag> skipped: re-tag`.
