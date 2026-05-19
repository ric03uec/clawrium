# Issue #401 — `clm gui` returns 404 for all pages after `uv tool install clawrium`

## Overview

The published wheel ships without the staged Next.js frontend, so `mount_frontend()`
short-circuits and every non-`/api/*` route 404s. Root cause is two-fold:

1. `src/clawrium/gui/frontend/` is gitignored (it is a build artifact of `make build-ui`),
   and Hatchling excludes gitignored files from the wheel by default. The
   `[tool.hatch.build.targets.wheel]` block in `pyproject.toml` only force-includes
   `skills/` — not the staged frontend — so the frontend never lands in the wheel.
2. The PyPI publish workflow runs `uv build` directly, bypassing the `make build`
   target that runs `build-ui` first. Even if hatch were configured to include the
   frontend, the directory would be empty when publishing from a fresh CI checkout.

Fix is mechanical and contained to three files plus one new test. No subtasks.

## Files to Modify

- `pyproject.toml` — add a `force-include` entry mapping `src/clawrium/gui/frontend`
  to `clawrium/gui/frontend` inside the wheel, alongside the existing `skills` entry.
- `.github/workflows/publish.yml` — replace the `uv build` step with `make build`
  so the frontend is staged before packaging. Node/npm must be available on the
  runner; `ubuntu-latest` already ships with Node, but verify the step.
- `tests/test_wheel_contents.py` *(new)* — regression test that builds the wheel
  (via `make build` or by running `uv build` after `make build-ui`) and asserts
  `clawrium/gui/frontend/index.html` is present inside the resulting `.whl`.

## Steps

1. **Update `pyproject.toml`** — extend the existing
   `[tool.hatch.build.targets.wheel.force-include]` table with:
   ```toml
   "src/clawrium/gui/frontend" = "clawrium/gui/frontend"
   ```
   Keep the existing `"skills" = "clawrium/_skills"` mapping. No other build
   config changes.

2. **Update `.github/workflows/publish.yml`** — replace:
   ```yaml
   - name: Build package
     run: uv build
   ```
   with a `make build` invocation. Because `make build` depends on `build-ui`,
   add a `Setup Node` step (`actions/setup-node@v4` with `node-version: 20` or
   the version `gui/package.json` requires) before the build step so `npm ci`
   succeeds. Keep `uv` setup as-is.

3. **Add wheel-contents regression test** — `tests/test_wheel_contents.py`:
   - Skip the test gracefully if the GUI hasn't been built locally (so plain
     `make test-py` without `make build-ui` doesn't fail for contributors who
     haven't installed Node). Detect this by checking
     `src/clawrium/gui/frontend/index.html` and `skipif` when absent.
   - When the staged frontend exists, run `uv build --wheel` into a tmp dir,
     open the produced wheel as a zipfile, and assert it contains
     `clawrium/gui/frontend/index.html` and `clawrium/_skills/` entries.
   - This is the regression net asked for in the acceptance criteria: any
     future config drift that drops the frontend from the wheel will fail this
     test when run against a built tree.

4. **Verify locally**:
   ```bash
   make clean
   make build
   uv tool install --force --reinstall ./dist/clawrium-*.whl
   clm gui --no-open --port 36000
   curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:36000/         # expect 200
   curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:36000/skills   # expect 200
   curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:36000/agents   # expect 200
   curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:36000/topology # expect 200
   curl -s http://127.0.0.1:36000/api/health                                # expect {"status":"ok",...}
   ```

5. **Run the suite**: `make test` and `make lint` must pass.

## Test Strategy

- **Automated**: New `tests/test_wheel_contents.py` builds the wheel and asserts
  presence of `clawrium/gui/frontend/index.html`. Existing `test_cli_gui.py`
  continues to cover the CLI surface.
- **Manual (acceptance criteria)**:
  - `make build` → install the wheel via `uv tool install` → confirm 200 on
    `/`, `/skills`, `/agents`, `/topology` and `/api/health` still returns ok.
  - Inspect the wheel with `unzip -l dist/clawrium-*.whl | grep frontend` to
    confirm `clawrium/gui/frontend/index.html` is present.
- **CI**: The publish workflow change cannot be exercised without cutting a
  release. Mitigation: dry-run the publish workflow logic locally (`make build`
  inside a clean checkout) and add a CI check for the wheel contents test on
  PRs so any regression is caught at PR time, not at release time.

## Risks & Notes

- **CI runner Node version**: `gui/package.json` may pin a Node version; the
  publish workflow needs `actions/setup-node@v4` with the matching version. If
  the project already has a `.nvmrc` or `engines` field, reuse it.
- **Wheel size**: Bundling the Next.js export adds bytes to the wheel. This is
  expected and unavoidable for an installable single-binary UX.
- **Source distribution (sdist)**: Hatch's `force-include` for the wheel target
  doesn't help sdists. If `uv build` produces an sdist that is later used to
  build a wheel (e.g. by downstream packagers), the frontend will still be
  missing. Out of scope for this issue — PyPI installs use the wheel directly.
  Worth a follow-up note if anyone reports it.
- **The CLAUDE.md says "version: 26.4.7" but pyproject.toml has 26.5.1.** Not
  blocking; flag for housekeeping.

## Subtasks

None — single task execution.

## Acceptance Criteria Mapping

| AC | Addressed by |
|----|--------------|
| `clm gui` serves all routes after `uv tool install` | Steps 1, 2 (force-include + make build in CI) |
| CI workflow runs `make build`, not `uv build` | Step 2 |
| Regression test/check fails if wheel ships without `frontend/index.html` | Step 3 |

---

<details>
<summary>Prompt Log</summary>

**Stage**: planning
**Skill**: /itx:plan-create
**Timestamp**: 2026-05-18T00:00:00Z
**Model**: claude-opus-4-7

```prompt
/itx-plan-create 401
```

</details>
