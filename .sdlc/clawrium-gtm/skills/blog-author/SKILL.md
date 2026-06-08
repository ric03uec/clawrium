---
name: clawrium-blog-author
description: Drafts a release blog post from a merged PR or set of merged PRs; outputs a markdown draft for human review.
version: 0.1.0
license: MIT
author: clawrium
platforms: [linux, macos]
metadata:
  cadence: "on-demand"
  trigger: "manual"
  outputs: ["markdown-draft"]
---

# blog-author

Drafts a short release blog post from one or more merged PRs. Output is a
markdown file for human review — it is never published automatically.

## Inputs

- PR number(s) P (one or more, space-separated)
- Repo: `ric03uec/clawrium`
- Output path: `~/sdlc-gtm/blog-drafts/<date>-draft.md`

## Steps

0. Clone or update the clawrium repo (preflight — fail immediately if this fails):
   ```bash
   REPO_DIR=~/clawrium-gtm
   if [ -d "$REPO_DIR/.git" ]; then
     git -C $REPO_DIR pull || { echo "[SKILL-BLOCKED]: cannot pull ric03uec/clawrium — check GITHUB_TOKEN"; exit 1; }
   else
     gh repo clone ric03uec/clawrium $REPO_DIR || { echo "[SKILL-BLOCKED]: cannot clone ric03uec/clawrium — check GITHUB_TOKEN"; exit 1; }
   fi
   ```

1. For each PR, fetch metadata:
   ```bash
   gh pr view <P> --repo ric03uec/clawrium --json title,body,mergedAt,url,files,author
   ```

2. Categorize each PR:
   - `feat` / `enhancement` → "What's New"
   - `fix` → "Bug Fixes"
   - `chore` / `docs` → skip (do not include in blog post)

3. Draft the blog post in markdown:
   ```markdown
   # Clawrium <version> — <date>

   <One paragraph intro — what this release is about>

   ## What's New
   <Bullet per feat PR — one sentence each, user-facing language>

   ## Bug Fixes
   <Bullet per fix PR — one sentence each>

   ---
   *Full changelog: [CHANGELOG.md](https://github.com/ric03uec/clawrium/blob/main/CHANGELOG.md)*
   ```

4. Write the draft to `~/sdlc-gtm/blog-drafts/<YYYY-MM-DD>-draft.md`.

5. Print the path to the draft. Do not open a PR or publish anywhere.

## Hard Constraints

- Never publish automatically. Output is a draft for human review only.
- Skip chore and docs PRs — blog posts are for user-facing changes only.
- Keep each bullet to one sentence. No marketing language ("revolutionary",
  "game-changing"). Describe what it does, not how great it is.
- If all PRs are chore/docs: write "No user-facing changes in this batch."
  and stop — do not create an empty draft.
