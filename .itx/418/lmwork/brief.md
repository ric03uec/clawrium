Work on issue #418 in this worktree. Read it first: `gh issue view 418`

## Status of the three issues in #418

- Issue 1 (path traversal in `serve_frontend`) is **ALREADY FIXED**. `src/clawrium/gui/server.py` has `_safe_serve` (lines 141-157) and uses it in all three candidate branches (lines 163, 167, 171). Do NOT touch this code. Do NOT re-implement `_safe_resolve`. The existing tests are in `tests/test_gui_server_static.py`.
- Issue 2 (TrustedHostMiddleware) is NOT done — implement it.
- Issue 3 (`secrets_file` leak) is NOT done — implement the scoped variant described below.

## Scope fence

Touch ONLY these files:

- `src/clawrium/gui/server.py` — add `TrustedHostMiddleware` to the middleware stack, right after the existing `CORSMiddleware.add_middleware` block.
- `src/clawrium/gui/routes/settings.py` — modify the `get_settings()` handler (function starting at line 20).
- `gui/src/lib/types.ts` — update the settings TypeScript interface (lines 340-344) to match the new response shape.
- Create `tests/test_gui_trusted_host.py` — new test file for Task 2.
- Create `tests/test_gui_settings_paths.py` — new test file for Task 3.

Do NOT touch:

- `src/clawrium/gui/server.py:141-179` (the `_safe_serve` helper and `serve_frontend`). Leave them exactly as-is.
- `src/clawrium/gui/routes/settings.py:34-88` (the `/version` and `/reset` endpoints).
- Any other route file, any Docusaurus doc, any test file besides the two new ones listed above.
- Any file under `gui/src/components/` — the fields you are keeping (`config_dir`, `usage_db`) are still consumed by the frontend, so nothing there needs to change.

## Tasks

### Task 2 — TrustedHostMiddleware

1. In `src/clawrium/gui/server.py`, add this import near the existing `CORSMiddleware` import:
   ```python
   from starlette.middleware.trustedhost import TrustedHostMiddleware
   ```
2. Right AFTER the `app.add_middleware(CORSMiddleware, ...)` block (currently lines 90-96), add:
   ```python
   app.add_middleware(
       TrustedHostMiddleware,
       allowed_hosts=[
           "localhost",
           "127.0.0.1",
           "localhost:36000",
           "127.0.0.1:36000",
           "testserver",  # TestClient's default Host header
       ],
   )
   ```
   The port `36000` matches `GUI_PORT` in `src/clawrium/core/server_lifecycle.py:57`. `"testserver"` is required so the existing test suite (`TestClient`) still works — verify with `make test` after the change.

3. Create `tests/test_gui_trusted_host.py`. Model the imports and structure on `tests/test_gui_cors.py` (short, uses `TestClient(app)` directly, one assertion per test). Include exactly these tests:
   - `test_allowed_host_localhost_accepted` — GET `/api/health` with `Host: localhost` → 200.
   - `test_allowed_host_loopback_accepted` — GET `/api/health` with `Host: 127.0.0.1:36000` → 200.
   - `test_foreign_host_rejected` — GET `/api/health` with `Host: attacker.example.com` → 400.
   - `test_foreign_host_with_port_rejected` — GET `/api/health` with `Host: evil.local:9999` → 400.

### Task 3 — `/api/settings` path redaction

1. In `src/clawrium/gui/routes/settings.py`, modify `get_settings()` (function at line 20) to return this exact dict shape:
   ```python
   return {
       "config_dir": str(config_dir),
       "usage_db": tracker.get_db_path(),
       "secrets_configured": (config_dir / "secrets.json").exists(),
   }
   ```
   That is: DROP `hosts_file`, `providers_file`, `secrets_file`. KEEP `config_dir` and `usage_db` — both are consumed by the frontend (`gui/src/components/settings/about-card.tsx`, `token-tracking-card.tsx`). ADD `secrets_configured` as a boolean.

2. In `gui/src/lib/types.ts`, update the interface (currently lines 340-344) to match:
   ```typescript
   config_dir: string;
   usage_db: string;
   secrets_configured: boolean;
   ```
   Remove the `hosts_file`, `providers_file`, `secrets_file` lines.

3. Create `tests/test_gui_settings_paths.py`. Model imports on `tests/test_gui_cors.py`. Include exactly these tests:
   - `test_settings_omits_secrets_file` — GET `/api/settings`, assert `"secrets_file"` NOT in response body keys.
   - `test_settings_omits_hosts_file` — assert `"hosts_file"` NOT in response body keys.
   - `test_settings_omits_providers_file` — assert `"providers_file"` NOT in response body keys.
   - `test_settings_reports_secrets_configured` — assert response has `secrets_configured` and its value is a `bool`.
   - `test_settings_keeps_config_dir_and_usage_db` — assert both `config_dir` and `usage_db` are still present (backward-compat for the two frontend cards).

## Pattern to follow

- Middleware add pattern: existing `CORSMiddleware` block in `src/clawrium/gui/server.py:90-96`.
- Test file pattern: `tests/test_gui_cors.py` (short, imports `app` from `clawrium.gui.server`, uses `TestClient(app)` directly).
- Return-dict style in settings routes: existing `get_version()` at `src/clawrium/gui/routes/settings.py:34`.

## Rules

- Commit locally on this worktree's current branch. Do NOT push. Do NOT open a PR.
- Do NOT add features, refactors, or abstractions beyond the tasks above. In particular:
  - Do NOT invent a `SETTINGS_SCHEMA_VERSION` or add versioning.
  - Do NOT touch `/api/settings/version` or `/api/settings/reset`.
  - Do NOT add a `secrets_configured` migration or fallback.
  - Do NOT edit `test_gui_server_static.py` or `test_gui_cors.py`.
- Run `make lint && make test` before committing. Both MUST pass. Fix any failures before you commit.
- Commit message body must reference `Closes #418` and follow the manual commit format in `AGENTS.md` (Co-Authored-By trailer).
- When finished (commit created, lint + tests green), run:
  ```bash
  echo done > .lmwork/418/worker.done
  ```
- If any task turns out to be already implemented or blocked, stop and write the reason to `.lmwork/418/worker.done` instead of proceeding.
