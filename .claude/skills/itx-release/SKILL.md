---
name: itx:release
description: Cut a new clawrium release — bump version, sync docs, tag, trigger PyPI publish
argument-hint: "[version]"
---
name: itx:release

# Release

Cut a new clawrium release end-to-end: bump version, sync docs, open a release PR, tag, trigger the PyPI publish workflow, and verify.

## Inputs

- `$ARGUMENTS` (optional): target version (e.g. `26.5.2` or `26.6.0`). If omitted, ask the user.

## Files this skill updates (the "known set")

Hard-coded list. The skill will edit exactly these and warn if it finds version-shaped strings elsewhere that look stale.

| File | What to update |
|------|----------------|
| `pyproject.toml` | `version = "<NEW>"` (line near top) |
| `uv.lock` | Re-run `uv sync` after editing `pyproject.toml`; the clawrium entry's `version` updates as a derived artifact. Stage and commit alongside `pyproject.toml`. |
| `AGENTS.md` | `- Version: <NEW>` line |
| `docs/installation.md` | `clawrium==<NEW>` and `clawctl, version <NEW>`. **Canonical install doc — edit this first, then mirror body verbatim into `website/docs/installation.md`.** |
| `website/docs/installation.md` | `clawrium==<NEW>` and `clawctl, version <NEW>`. Mirror of `docs/installation.md`; body must stay identical (only the Docusaurus frontmatter and mirror-warning comment at the top differ). |
| `website/docs/guides/quickstart.md` | `clawrium==<NEW>` |
| `website/docs/scenarios/101.md` | `clawctl <NEW>` |
| `CHANGELOG.md` (root) | Archive the current contents to `docs/releases/<NEW>/CHANGELOG.md`, then reset this file to the empty `[Unreleased]` template. See Phase 1 step 6a. |
| `docs/releases/<NEW>/CHANGELOG.md` | New per-release archive folder created from the root changelog at cut time. See Phase 1 step 6a. |

Do NOT touch:
- `docs/agent-support/hermes.md` — that's the hermes upstream agent version, not clawrium.
- `website/package.json`, `gui/package.json` — independent subpackages.
- `src/clawrium/platform/registry/**` and `tests/**` — those are agent-type fixtures, not clawrium's version.

## Instructions

### Phase 0 — Pre-flight

1. **Determine target version**. If `$ARGUMENTS` is empty, read current from `pyproject.toml`:
   ```bash
   CURRENT=$(grep -m1 '^version' pyproject.toml | sed 's/.*"\(.*\)"/\1/')
   ```
   Ask the user: "Current is `$CURRENT`. Target version?" Stop until answered.

2. **Sanity checks** (all must pass — if any fail, stop and report):
   ```bash
   git status --porcelain                       # must be empty (modulo untracked tmp/ slides/)
   git rev-parse --abbrev-ref HEAD              # must be 'main'
   git fetch origin main
   git rev-list --count HEAD..origin/main       # must be 0 (local up-to-date)
   gh auth status                               # must be authenticated
   ```

3. **Confirm `<NEW>` is not already tagged**:
   ```bash
   git tag -l "v<NEW>"                          # must be empty
   ```

4. **Run lint + tests** before touching anything:
   ```bash
   make lint && make test
   ```

### Phase 1 — Bump + doc sync (PR)

5. **Branch**:
   ```bash
   git checkout -b release/v<NEW>
   ```

6. **Apply edits** to every file in the known set. Use the Edit tool — exact string matches only, no regex sweeps. After each edit, the file's *previous* version string (e.g. `26.5.1`) must no longer appear in that file (verify with grep).

6a. **Archive + reset the changelog**. The root `CHANGELOG.md` is the working
    log for the just-finished release. Freeze it into a per-version archive,
    then reset the root to an empty template for the next cycle:
    ```bash
    mkdir -p docs/releases/<NEW>
    cp CHANGELOG.md docs/releases/<NEW>/CHANGELOG.md
    ```
    Then edit `docs/releases/<NEW>/CHANGELOG.md`:
    - Replace the top-of-file "working changelog" preamble with a release-specific
      header (title `# Release <NEW>`, a note that it is the frozen archive, and a
      back-link to the root `CHANGELOG.md`).
    - Rename the `## [Unreleased]` heading to `## [<NEW>]`.
    - Confirm no `Unreleased` references remain: `grep -ni unreleased docs/releases/<NEW>/CHANGELOG.md`.

    Then reset the root `CHANGELOG.md` to the empty template — keep the
    `# Changelog` preamble and the `docs/releases/` archive note, drop all
    shipped entries, and leave a bare `## [Unreleased]` with empty
    `### BREAKING` / `### Added` / `### Changed` / `### Fixed` / `### Documentation` /
    `### Internal` subsections. Use the existing archived release as the
    structural reference (see `docs/releases/26.6.0/CHANGELOG.md`, the first
    one created under this convention).

7. **Stale-mention scan** (warn, don't auto-fix):
   ```bash
   git grep -nE 'clawrium[^a-z]+(==|version )[0-9]+\.[0-9]+\.[0-9]+' \
     -- ':!tests' ':!src/clawrium/platform/registry' ':!website/build' \
     ':!docs/agent-support/hermes.md' ':!**/node_modules/**'
   ```
   Any line with a version other than `<NEW>` → flag to the user before committing.

8. **Diff-scope guard** (this is the safety net for the "no ATX on release PRs" carve-out — release PRs skip automated review, so the skill must hard-fail if non-mechanical files crept in):
   ```bash
   KNOWN_SET='^(pyproject\.toml|uv\.lock|AGENTS\.md|CHANGELOG\.md|docs/installation\.md|docs/releases/.*|website/docs/installation\.md|website/docs/guides/quickstart\.md|website/docs/scenarios/101\.md|CONTRIBUTING\.md|\.claude/skills/itx-release/SKILL\.md|tests/test_demo_assets\.py)$'
   UNEXPECTED=$(git diff --name-only main...HEAD | grep -vE "$KNOWN_SET" || true)
   if [ -n "$UNEXPECTED" ]; then
     echo "BLOCKED: release branch touches files outside the known set:"
     echo "$UNEXPECTED"
     echo "These changes need an ATX-reviewed PR before they ship in a release. Abort."
     exit 1
   fi
   ```
   Stop and surface the list to the user; do not auto-stage or proceed past this check. If the extra files are genuinely needed for the release, open a separate ATX-reviewed PR first, merge it, then rebase the release branch.

9. **Verify**:
   ```bash
   make lint && make test
   ```

10. **Commit + push**:
    ```bash
    git add pyproject.toml uv.lock AGENTS.md CHANGELOG.md docs/releases/ docs/installation.md website/docs/
    git commit -m "chore(release): bump to v<NEW> + sync doc versions"
    git push -u origin release/v<NEW>
    ```

11. **Open PR** (manual review only — do NOT request ATX review for release bumps):
    ```bash
    gh pr create --title "chore(release): v<NEW>" --body "$(cat <<EOF
    ## Summary
    - Bump \`clawrium\` to v<NEW>
    - Sync version mentions in AGENTS.md + website docs

    ## Testing
    - [x] \`make lint\` passes
    - [x] \`make test\` passes

    Closes nothing — release housekeeping.
    EOF
    )"
    ```
    Print the PR URL and **stop**. Ask the user to merge it. Do not auto-merge.

### Phase 2 — Tag + push (after merge)

12. **Wait for the user to confirm the PR is merged**, then:
    ```bash
    git checkout main
    git pull --ff-only origin main
    grep -m1 '^version' pyproject.toml          # confirm <NEW> landed
    ```

13. **Tag and push**:
    ```bash
    git tag -a v<NEW> -m "v<NEW>"
    git push origin v<NEW>
    ```

### Phase 3 — Trigger publish + verify

14. **Create the GitHub release** (this is what `publish.yml` listens for):
    ```bash
    gh release create v<NEW> --title "v<NEW>" --generate-notes
    ```
    `--generate-notes` builds the changelog from merged PRs since the previous tag.

15. **Watch the workflow**:
    ```bash
    RUN_ID=$(gh run list --workflow=publish.yml --limit=1 --json databaseId -q '.[0].databaseId')
    gh run watch "$RUN_ID" --exit-status
    ```
    If it fails, stop and report the failed step. Common failure modes:
    - Lint/test regressions (rare — Phase 0 caught them, but the published build runs them again)
    - PyPI trusted-publisher misconfig — needs human

16. **Verify on PyPI**:
    ```bash
    sleep 30                                    # PyPI propagation
    pip index versions clawrium 2>&1 | grep -F "<NEW>"
    ```
    Also print:
    ```
    PyPI: https://pypi.org/project/clawrium/<NEW>/
    GitHub: https://github.com/ric03uec/clawrium/releases/tag/v<NEW>
    ```

17. **Report** to the user:
    ```
    ## Release v<NEW> — Shipped

    - PR: <url>
    - Tag: v<NEW>
    - Workflow run: <url>
    - PyPI: https://pypi.org/project/clawrium/<NEW>/
    - Install: `uv tool install clawrium@<NEW>`
    ```

## Failure recovery

- **PR has lint/test failure** → fix on the release branch, push again, re-run Phase 1 step 9.
- **Tag pushed but release not created** → `gh release create v<NEW> --title "v<NEW>" --generate-notes` (idempotent fix).
- **Publish workflow failed** → do NOT delete the tag. Identify the failed step from `gh run view <RUN_ID>`; fix on `main` via a follow-up PR + new patch tag (`v<NEW+1>`). Yanking a published version is worse than shipping a patch.
- **PyPI says version exists already** → `<NEW>` was published earlier and re-uploading is blocked. Pick the next patch.

## Anti-patterns

- Bumping `pyproject.toml` on `main` directly. Always go through a release branch + PR.
- Tagging before the PR is merged. The tag must point at a commit that exists on `main`.
- Editing files outside the "known set" without flagging it to the user first.
- Running ATX review on release PRs — content is mechanical and ATX cost is wasted.
- Force-pushing the tag if you "fixed" something post-release. Cut a new patch instead.

## Prompt Logging

**REQUIRED**: Append a prompt log to `.itx/<release-issue>/00_RELEASE.md` if a GitHub issue tracks the release. If no issue, write to `.itx/release-v<NEW>/00_RELEASE.md`.

See [AGENTS.md](../../../AGENTS.md#prompt-logging-standard) for format.
