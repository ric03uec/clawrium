CORRECTION to the brief for #418. Read this BEFORE writing the tests.

Two changes to the test plan and one change to the middleware config. A pre-implementation review of the brief flagged them; the fixes are cheap now, expensive after.

1. `TrustedHostMiddleware` — do NOT include `"testserver"` in `allowed_hosts`. Hardcoding it in production would let any client bypass the check with `Host: testserver`. Use these five entries and no more: `"localhost"`, `"127.0.0.1"`, `"localhost:36000"`, `"127.0.0.1:36000"`. In `tests/test_gui_trusted_host.py`, construct the client as `TestClient(app, base_url="http://localhost:36000")` so requests carry a real allowed host. Do this in every test in that file.

2. `tests/test_gui_settings_paths.py` — replace `test_settings_reports_secrets_configured` with TWO parametrized cases. Use a `tmp_path` fixture that patches `clawrium.gui.routes.settings.get_config_dir` (via `monkeypatch.setattr`) to point at a tmp dir. Case A: create `<tmp>/secrets.json` first, hit `GET /api/settings`, assert `response.json()["secrets_configured"] is True`. Case B: leave the dir empty, assert `response.json()["secrets_configured"] is False`. Both cases must use `TestClient(app, base_url="http://localhost:36000")` for compatibility with the new TrustedHostMiddleware.

3. `test_settings_keeps_config_dir_and_usage_db` — strengthen the asserts: check the values are non-empty strings, not just present. Use `assert isinstance(response.json()["config_dir"], str) and response.json()["config_dir"]`.

Nothing else in the brief changes. Do not add extra tests, do not touch other files, do not change the `secrets_configured` implementation formula. Retaining `config_dir` and `usage_db` is an accepted trade-off (both fields are consumed by frontend cards); mention this trade-off in the commit body under a "Residual exposure" line.

Adding `CHANGELOG.md` under `[Unreleased] ### Fixed` is correct per AGENTS.md — keep it.
