# Issue #620 — Implementation Plan

`bug(deps): jinja2 missing from runtime dependencies — clawctl agent sync crashes on fresh install`

## Root Cause

Concrete trace:

1. `pyproject.toml` `[project].dependencies` (lines 14–38) lists every runtime dep
   for the `clawrium` distribution — but **not** `jinja2`.
2. `jinja2>=3.0.0` is declared only under `[dependency-groups].dev` at
   `pyproject.toml:92`. The PEP 735 `dependency-groups` table is a *developer*
   concept consumed by `uv sync` / `uv run --group dev` in a checkout. It is
   **not** part of the wheel/sdist metadata and is **never** installed by
   `uv tool install <pkg>` or `pip install <pkg>`.
3. `uv tool install --reinstall clawrium` therefore creates an isolated venv
   that contains the 25 runtime deps from `[project].dependencies` and nothing
   else. `jinja2` is absent.
4. `clawctl agent sync <hermes-agent>` enters the hermes render path. The
   hermes-canonical and hermes-systemd renders both call `_hermes_template()`
   in `src/clawrium/core/render.py` — three sites: `render.py:766`,
   `render.py:945`, `render.py:1150`. Each does a function-local
   `from jinja2 import Environment, StrictUndefined`.
5. First call raises `ModuleNotFoundError: No module named 'jinja2'`, killing
   the sync at `render.py:766` exactly as reported.

The regression was introduced by #614 / #618 (the new hermes multi-provider
render path under #589). Pre-#614 the only consumer was `core/launchd.py`,
which is imported only from `core/lifecycle_macos.py` — a macOS-only code path
that no Linux user (e.g. wolf-i) exercises. So the dev-group-only declaration
was latent: it worked in CI (which installs the dev group) and worked on
contributor checkouts (`uv sync`), but shipped wheels never had jinja2.

## Approach

**One-line fix:** add `"jinja2>=3.0.0",` to `[project].dependencies` in
`pyproject.toml` (alphabetical-ish slot near `jsonschema` is fine; matching
the existing style — no inline comment needed).

**Open question: also keep the dev-group copy, or remove it?**

**Recommendation: remove the dev-group entry.** Justification:

- Once jinja2 is a runtime dep, `uv sync` (and `uv sync --group dev`) will
  install it transitively for every dev workflow — tests, lint, ruff, etc.
  The dev-group entry becomes redundant.
- Two declarations create a future drift hazard: someone bumping the runtime
  pin would have to remember to bump the dev pin in lockstep, or pytest could
  silently resolve a different jinja2 than production.
- "Parity with existing tests" is already preserved — tests import `jinja2`
  and will continue to find the runtime copy.
- Keeping both is harmless *today* but adds zero value and one foot-gun.

Net change to `pyproject.toml`: +1 line in `[project].dependencies`, −1 line
in `[dependency-groups].dev`.

## Regression Coverage

**Proposed check:** add a smoke test at `tests/test_runtime_imports.py` that
imports every module which has a runtime dep on a third-party package, asserting
the package resolves from the installed environment (not the dev group).

Minimal viable form (one test, ~10 lines):

```python
# tests/test_runtime_imports.py
def test_jinja2_is_runtime_dep():
    """Guards #620: jinja2 must ship in [project].dependencies, not dev-only.

    core/render.py and core/launchd.py both import jinja2; a fresh
    `uv tool install clawrium` must satisfy those imports without dev extras.
    """
    import tomllib
    from pathlib import Path

    pyproject = tomllib.loads(
        (Path(__file__).parent.parent / "pyproject.toml").read_text()
    )
    runtime = " ".join(pyproject["project"]["dependencies"])
    assert "jinja2" in runtime, (
        "jinja2 was dropped from [project].dependencies; "
        "see #620 — clawctl agent sync will crash on fresh installs"
    )
```

**Why this over `uv pip check` in CI:** `uv pip check` only verifies declared
deps resolve consistently — it cannot detect a *missing* declaration, because
nothing else in the runtime deps tree asks for jinja2. A pyproject assertion
test catches the exact failure mode of #620 (declaration drift back to
dev-only) and runs in the existing `make test` matrix with zero new CI plumbing.

A heavier alternative — actually running `uv tool install` from the built
wheel and invoking `clawctl agent sync` against a dummy host — would be more
faithful but is far too expensive for unit-test CI. The pyproject assertion is
the smallest test that fails for the specific regression we care about.

## Risks

1. **Other lazy jinja2 imports.** Three sites in `core/render.py` (lines 766,
   945, 1150) all do function-local imports — moving jinja2 to runtime deps
   fixes all three identically; there is no per-site work. `core/launchd.py`
   imports jinja2 at module top level (`import jinja2` at line 26), but it is
   only reached via `core/lifecycle_macos.py` — macOS-only. The fix unblocks
   that path too, but it's worth noting macOS users would hit a *worse* failure
   (ImportError at module load, not at function call) on a fresh install. No
   additional code changes needed.

2. **Pinned versions elsewhere.** No other pin of jinja2 found in the repo
   (`grep -rn jinja2 src tests` returns only imports, no `==`/`>=` pins outside
   `pyproject.toml`). The Ansible playbooks under `playbooks/` are executed via
   `ansible-runner` on the **remote** host, not in the clawctl venv — they use
   the remote's system Python and are unaffected.

3. **uv lock churn.** Adding a runtime dep will produce a non-trivial diff in
   `uv.lock` (if it is committed). Reviewers should expect the lockfile delta
   alongside the one-line pyproject change. Not a real risk, just an FYI.

4. **CI behavior on the dev-group removal.** Existing tests
   (`tests/test_gitconfig_template.py`, `tests/test_hermes_configure.py`,
   etc.) import `jinja2` at module level. If the dev-group entry is dropped
   but jinja2 has *not* been added to runtime deps in the same commit, the
   whole test suite breaks. Apply both changes atomically (single commit).

5. **Wheel build / hatch.** `jinja2` is a pure-Python package and adds no
   binary build complexity. Wheel size grows by ~140 KB. No `hatch` config
   changes required.

## Files To Modify

- `pyproject.toml` — add `"jinja2>=3.0.0",` to `[project].dependencies`,
  remove the same string from `[dependency-groups].dev`.
- `tests/test_runtime_imports.py` *(new, ~15 lines)* — pyproject assertion test
  guarding the declaration.
- `uv.lock` *(auto-regenerated by `uv lock` / `uv sync`)* — committed.
- `CHANGELOG.md` under `## [Unreleased]` → `### Fixed`: one-line entry
  ("Fixed `clawctl agent sync` crashing with `ModuleNotFoundError: jinja2`
  on fresh `uv tool install clawrium` (#620).").

## Verification (post-fix, manual)

1. `make test` (new test passes; existing test suite still green).
2. `make lint`.
3. Build a wheel locally (`uv build`) and `uv tool install --reinstall
   --from dist/clawrium-*.whl clawrium`, then `python -c "import jinja2"`
   inside the tool venv — should succeed.
4. Optional but recommended: on wolf-i, repeat the exact #620 repro
   (`uv tool install --reinstall clawrium` once published, or against the
   local wheel) and confirm `clawctl agent sync <hermes-agent>` no longer
   raises.

## Subtasks

None — atomic single-file fix plus a guard test.

---

<details>
<summary>Prompt Log</summary>

**Stage**: planning
**Skill**: /itx:plan-create
**Timestamp**: 2026-06-05T00:00:00Z
**Model**: claude-opus-4-7

```prompt
/itx-plan-create 620

Orchestrator handoff notes (parent #589 follow-up bugs):
- This is a PLAN-ONLY session. Do NOT implement, do NOT commit, do NOT open a PR. Stop after writing .itx/620/00_PLAN.md and posting the plan as a comment on issue #620.
- This worktree (/home/devashish/workspace/ric03uec/clawrium-issue-620, branch issue-620-jinja-runtime-dep) is yours; investigate from here.
- Do NOT create subtask issues — this bug is atomic, single-file fix scope.
- Required output in the plan:
  1. Root cause — concrete trace through pyproject.toml and core/render.py:766 showing exactly why a fresh `uv tool install` doesn't get jinja2.
  2. Approach — one-line fix (move `jinja2>=3.0.0` from [dependency-groups].dev to [project].dependencies) PLUS the question: should we ALSO keep it in dev for parity with existing tests, or remove the dev copy? Recommend one and justify.
  3. Regression coverage — propose ONE specific test/check that would catch a future drop (e.g., `uv pip check` step in CI, or an importability smoke test in tests/).
  4. Risks — anything subtle. e.g., does any other code path lazy-import jinja2 that we should verify works too? Are there pinned versions elsewhere?
- Found during end-to-end validation of #589 on wolf-i. Repro: `uv tool install --reinstall clawrium && clawctl agent sync <hermes-agent>` → ModuleNotFoundError at core/render.py:766.
- After the plan is written and posted as a comment on #620, STOP. The user will pick up implementation manually.
```

**Output**: `.itx/620/00_PLAN.md` written; plan posted as comment on issue #620.

</details>
