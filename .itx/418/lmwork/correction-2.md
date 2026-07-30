CORRECTION 2 — read before touching allowed_hosts again.

You correctly identified that existing tests default to `Host: testserver`. Do NOT put `"testserver"` back in the production `allowed_hosts` — that is exactly the vulnerability class this issue exists to close.

Instead, update the existing tests to send a real allowed Host header. The scope fence is widened for this purpose ONLY:

- You MAY edit `tests/test_gui_cors.py` — replace every `TestClient(app)` with `TestClient(app, base_url="http://localhost:36000")`. Do not change any assertions.
- You MAY edit `tests/test_gui_server_static.py` — same substitution wherever it uses `TestClient`. Do not change any assertions.
- You MAY edit any other existing test file whose tests break for the same reason (missing allowed Host). Same fix: change the `TestClient(app)` constructor to `TestClient(app, base_url="http://localhost:36000")`. Do NOT modify test logic — only the constructor call.

Then in `src/clawrium/gui/server.py`, keep `allowed_hosts` at exactly these four values and nothing else: `"localhost"`, `"127.0.0.1"`, `"localhost:36000"`, `"127.0.0.1:36000"`.

Run `make test` after the sweep. Every test that failed due to the Host header must pass. Any other pre-existing failure is not yours to fix.

Nothing else changes.
