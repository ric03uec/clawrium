---
name: clawrium-release-announcements
description: Daily — draft a release blog post, open a PR, iterate on comments until merged
version: 0.2.0
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
release that has not yet been processed, draft a release blog post, open a PR,
post a Discord announcement, and enter an iteration loop: poll the PR for new
comments every 30 minutes, address feedback, and only complete when the PR is
merged. Skip releases whose tag range contains zero commits (re-tags).

## When to Use

- Triggered by a daily cron that sends a "check for new clawrium releases"
  request to the agent.
- Triggered ad-hoc by an operator request such as
  "check `ric03uec/clawrium` for new releases" or "produce a release
  announcement for `v<version>`".

Do **not** run this skill more than once per release tag — the procedure is
idempotent (it re-queries GitHub and kanban for existing artifacts before
writing), but the intent is one announcement per release.

## Quick Reference

| Phase     | Action                                                                                  |
|-----------|-----------------------------------------------------------------------------------------|
| Discover  | `gh release list --repo ric03uec/clawrium --limit 10`; filter unprocessed tags          |
| Triage    | `git log <prev_tag>..<tag>` — skip if zero commits; classify the rest                   |
| Draft     | Write blog markdown per `skills/clawrium/blog-author/SKILL.md` rules                   |
| PR        | Create branch `blog/<tag>-<slug>`, commit file, push, open PR                          |
| Discord   | Post short announcement in `#announcements`                                             |
| Iterate   | Poll PR comments every 30 min, apply feedback, push fixes                              |
| Complete  | Move kanban task to Done once PR is merged; record tag in memory                       |

## Procedure

### Phase 1: Discovery

For each release published since the last successful run of this skill:

1. **Fetch the release.**

   ```bash
   gh release view <tag> --repo ric03uec/clawrium --json body,publishedAt,tagName,url
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

   Apply the triage rules from `skills/clawrium/blog-author/SKILL.md` to
   classify each commit as user-facing, under-the-hood, or drop.

### Phase 2: Draft

4. **Draft the blog post.**

   Follow the **output structure**, **voice**, and **anti-patterns** sections
   of `skills/clawrium/blog-author/SKILL.md`. The post body MUST use that
   skill's required structure (What changed → Why → Try it → Links) and word
   budget (~250–400 words).

   Front-matter (Docusaurus list form):

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
   `website/blog/<YYYY-MM-DD>-v<version>-release.md`.

### Phase 3: PR Creation

5. **Check for an existing PR.**

   ```bash
   gh pr list --repo ric03uec/clawrium --head blog/<tag>-<slug> --state open --json number,url
   ```

   If an open PR already exists for this branch, skip creation and record the
   PR number for iteration. Reply with the existing PR URL and continue to
   Phase 5.

6. **Check for an existing kanban card.**

   ```bash
   hermes kanban list --board blog-pipeline --json
   ```

   Search for a card titled exactly `Blog draft: clawrium v<version>`. If one
   exists, record its task_id; otherwise create it:

   | Field    | Value                                                       |
   |----------|-------------------------------------------------------------|
   | Board    | Blog Pipeline                                               |
   | Lane     | Ready                                                       |
   | Assignee | `default`                                                   |
   | Title    | `Blog draft: clawrium v<version>`                           |
   | Body     | PR URL (will be added after PR creation)                   |

7. **Create the branch and commit.**

   ```bash
   cd ~/clawrium
   git checkout main
   git pull origin main
   git checkout -b blog/<tag>-<slug>
   ```

   Write the blog file:

   ```bash
   mkdir -p website/blog
   # Write the draft to website/blog/<YYYY-MM-DD>-v<version>-release.md
   ```

   Commit and push:

   ```bash
   git add website/blog/<YYYY-MM-DD>-v<version>-release.md
   git commit -m "blog: v<version> release notes"
   git push -u origin blog/<tag>-<slug>
   ```

   If `git push` fails with 403:

   ```
   blocker: PAT lacks repo scope — cannot push branch. Regenerate PAT with repo scope and re-run.
   ```

   Stop here. Do not attempt workarounds.

8. **Open the PR.**

   ```bash
   gh pr create --repo ric03uec/clawrium \
     --base main \
     --head blog/<tag>-<slug> \
     --title "blog: v<version> release notes" \
     --body "$(cat <<'EOF'
   ## What changed

   <one-line summary of the release>

   ## Release notes

   <link to GitHub release>

   ---

   Draft blog post for review. Will iterate on comments.
   EOF
   )"
   ```

   Record the PR number and URL.

9. **Update kanban card with PR link.**

   Add the PR URL to the kanban card body so the card tracks the PR state.

### Phase 4: Discord Announcement

10. **Check Discord for a recent announcement.**

    Read the last 7 days of messages in the `#announcements` channel. If any
    message mentions `v<version>`, do **not** repost — reply with the existing
    message id and continue to Phase 5.

11. **Post the Discord announcement.**

    Single message in `#announcements`, ≤500 characters, no markdown headers,
    no `@here` / `@everyone`:

    ```
    clawrium v<version> is out

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

### Phase 5: Iteration Loop

12. **Enter PR iteration loop.**

    This skill is designed to be re-entrant. Each scheduled run (every 30
    minutes) should:

    a. **Load state**: Query the kanban card for this release. If the card is
       already in `Done` state, skip — the release is fully processed.

    b. **Check PR state**:

       ```bash
       gh pr view <pr_number> --repo ric03uec/clawrium --json state,mergedAt,closedAt,comments,reviews
       ```

       - If `state == "MERGED"`: Apply any final review feedback, move kanban
         card to `Done`, record tag in memory, reply with completion status.
       - If `state == "CLOSED"` and not merged: Move card to `Done` with
         `outcome: cancelled`, record tag in memory, reply with cancellation.
       - If `state == "OPEN"`: Continue to comment processing.

    c. **Process new comments**:

       Fetch all PR comments and review comments. Compare against the last
       processed comment timestamp stored in the kanban card metadata.

       For each new comment:
       - Parse the feedback
       - Apply changes to the blog file
       - Commit with message: `blog: address review feedback — <summary>`
       - Push to the branch
       - Reply to the PR comment confirming the fix (if the comment is from a
         reviewer who can see replies)

       Update the card metadata with the latest processed comment timestamp.

    d. **Update kanban card**:

       - Lane: `In Progress` (while iterating)
       - Metadata: `{ "pr_number": <n>, "pr_url": "<url>", "last_comment_processed": "<iso8601>" }`

    e. **Reply with status**:

       ```
       release=<tag> pr=<url> status=iterating comments_processed=<N> waiting_for_review
       ```

13. **Polling interval**.

    The skill should be scheduled to run every 30 minutes. Each run performs
    one iteration step (check PR state, process comments, update).

### Phase 6: Completion

14. **On PR merge**:

    - Move kanban card to `Done` lane
    - Set card metadata: `{ "outcome": "merged", "merged_at": "<iso8601>", "pr_number": <n> }`
    - Add kanban comment: `PR merged — blog published`
    - Persist `<tag>` in agent memory under `clawrium-release-announcements:processed`

15. **Reply**:

    ```
    release=<tag> pr=<url> status=merged blog_published=true
    ```

## State Tracking

Each kanban card for this workflow must track:

```json
{
  "pr_number": 123,
  "pr_url": "https://github.com/ric03uec/clawrium/pull/123",
  "last_comment_processed": "2026-05-31T22:30:00Z",
  "outcome": null
}
```

The `last_comment_processed` timestamp enables idempotent comment processing
across re-entrant runs.

## Configuration Required

| Requirement                                            | Failure reply                                |
|--------------------------------------------------------|----------------------------------------------|
| `gh` CLI installed and authenticated for `ric03uec/clawrium` | `config-error: gh auth`                |
| PAT with `repo` scope (for pushing branches)           | `config-error: PAT lacks repo scope`         |
| Blog Pipeline kanban board exists                      | `config-error: Blog Pipeline board missing`  |
| `Ready` lane exists on Blog Pipeline                   | `config-error: Ready lane missing`           |
| Profile named `default` exists                         | `config-error: default profile missing`      |
| Discord channel attachment named `announcements`       | `config-error: announcements channel missing`|

On any `config-error:`, stop the run for that release; do not partially
publish.

## Content Rules

Blog body rules (triage, output structure, hard constraints, voice,
anti-patterns) live in `skills/clawrium/blog-author/SKILL.md` and apply
unchanged. Do NOT duplicate those rules here.

Differences from `blog-author`:

| Aspect              | `blog-author`             | this skill                                              |
|---------------------|---------------------------|---------------------------------------------------------|
| Output surface      | One PR per feature        | One PR per release (can bundle multiple features)       |
| Author front-matter| `author: maurice`         | `authors: [maurice]` (Docusaurus list form)             |
| Cadence             | Every 30 min, poll        | Daily discovery + 30-min iteration loop                 |
| Side effect         | None                      | Posts Discord announcement; iterates on comments        |
| Completion trigger  | PR opened                 | PR merged                                               |

Discord format is specified inline in Phase 4 (steps 10-11).

## Pitfalls

- Combining multiple releases into a single PR or Discord message.
- Inventing `clawctl` commands or option names not present in
  `src/clawrium/cli/`.
- Discord posts containing `@here`, `@everyone`, or any role ping.
- Auto-drafting a release announcement for a security fix — flag for a
  human and skip the announcement entirely.
- Pushing directly to `main`. Always use a feature branch.
- Publishing the blog before PR merge. The PR merge is the publication gate.
- Silently swallowing missing configuration. Always reply
  `config-error: <what>` and stop.
- Processing the same comment twice across iterations. Use the timestamp
  gate.
- Leaving the kanban card in `Ready` or `In Progress` after PR merge. Must
  move to `Done`.

## Verification

For each release processed in a run, all of the following MUST be true at
completion:

- A PR titled `blog: v<version> release notes` exists on
  `ric03uec/clawrium` (either open, closed, or merged).
- A Discord message in `#announcements` mentions `v<version>` and contains
  the upgrade command and the GitHub release URL.
- A kanban card titled `Blog draft: clawrium v<version>` exists on Blog
  Pipeline in the `Done` lane with `outcome: merged` in metadata.
- The tag `<tag>` is present in agent memory under
  `clawrium-release-announcements:processed`.

For releases skipped because of zero commits:

- No PR exists for that version.
- No Discord message references that version.
- No kanban card exists for that version.
- The reply line is `release=<tag> skipped: re-tag`.
