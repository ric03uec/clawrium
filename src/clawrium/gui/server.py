"""FastAPI server for Clawrium GUI.

Serves the static Next.js frontend and provides REST API
endpoints for fleet management, token tracking, and chat.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from clawrium.core import web_ui_tunnel
from clawrium.gui.routes import (
    agents,
    fleet,
    integrations,
    providers,
    settings,
    skills,
    topology,
    usage,
)

logger = logging.getLogger(__name__)

# Reaper cadence. The web-ui /web-ui handler stamps a per-agent last-access
# timestamp; this task sweeps the map every 5 minutes and closes any tunnel
# that has been idle for more than 30 minutes.
WEB_UI_REAPER_INTERVAL_S = 300.0
WEB_UI_REAPER_THRESHOLD_S = 1800.0


@asynccontextmanager
async def lifespan(app: FastAPI):
    """App lifespan: start the web-ui tunnel reaper, drain on shutdown."""

    async def _reaper_loop() -> None:
        while True:
            try:
                await asyncio.sleep(WEB_UI_REAPER_INTERVAL_S)
                closed = await fleet.reap_idle_tunnels(WEB_UI_REAPER_THRESHOLD_S)
                if closed:
                    logger.info("web-ui reaper closed %d idle tunnel(s)", closed)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — keep the loop alive
                logger.exception("web-ui reaper iteration failed")

    task = asyncio.create_task(_reaper_loop(), name="web-ui-reaper")
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        # close() does a SIGTERM→busy-wait→SIGKILL dance that can block up
        # to ~2 s per tunnel. Run sequentially via asyncio.to_thread so the
        # event loop isn't blocked and uvicorn's graceful-shutdown budget
        # isn't exceeded when multiple tunnels are open.
        keys = list(fleet.WEB_UI_LAST_ACCESS.keys())
        for key in keys:
            try:
                await asyncio.to_thread(web_ui_tunnel.close, key)
            except Exception:  # noqa: BLE001
                logger.debug("shutdown close failed for %s", key, exc_info=True)
        fleet.WEB_UI_LAST_ACCESS.clear()


app = FastAPI(
    title="Clawrium GUI",
    description="Local web dashboard for AI assistant fleet management",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:36000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routers
app.include_router(fleet.router)
app.include_router(topology.router)
app.include_router(providers.router)
app.include_router(settings.router)
app.include_router(usage.router)
app.include_router(agents.router)
app.include_router(integrations.router)
app.include_router(skills.router)


@app.get("/api/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "service": "clawrium-gui"}


def mount_frontend(app: FastAPI) -> None:
    """Mount the static frontend with SPA-style routing.

    Next.js static export generates files like:
      - /index.html (for /)
      - /topology.html (for /topology)
      - /agents.html (for /agents)

    We mount /_next as a static directory for assets, then
    add a catch-all route that resolves paths to .html files.
    """
    frontend_dir = Path(__file__).parent / "frontend"
    if not frontend_dir.exists() or not (frontend_dir / "index.html").exists():
        return

    # Mount _next directory for JS/CSS assets
    next_dir = frontend_dir / "_next"
    if next_dir.exists():
        app.mount(
            "/_next",
            StaticFiles(directory=str(next_dir)),
            name="next-assets",
        )

    frontend_root = frontend_dir.resolve()

    def _safe_serve(candidate: Path) -> FileResponse | None:
        """Return FileResponse only if candidate stays inside frontend_root.

        Starlette normalises plain `../` in URL paths, but percent-encoded
        traversal (`%2e%2e`) and unicode normalisation edge cases are not
        guaranteed across all versions. The resolve()+is_relative_to()
        check is the defense-in-depth guard recommended by ATX B5.
        """
        try:
            resolved = candidate.resolve()
        except OSError:
            return None
        if not resolved.is_relative_to(frontend_root):
            return None
        if not resolved.is_file():
            return None
        return FileResponse(resolved)

    @app.get("/{path:path}")
    async def serve_frontend(request: Request, path: str) -> Response:
        """Serve static HTML pages for frontend routes."""
        # Try exact file first (e.g. favicon.ico)
        if (resp := _safe_serve(frontend_dir / path)) is not None:
            return resp

        # Try path + .html (e.g. /topology -> topology.html)
        if (resp := _safe_serve(frontend_dir / f"{path}.html")) is not None:
            return resp

        # Try path/index.html (for trailing slash dirs)
        if (resp := _safe_serve(frontend_dir / path / "index.html")) is not None:
            return resp

        # Fallback to index.html for client-side routing. Containment is
        # guaranteed here because the path is a literal constant.
        index = frontend_dir / "index.html"
        if index.is_file():
            return FileResponse(index)
        raise HTTPException(status_code=404)


# Mount frontend static files (noop if not built yet)
mount_frontend(app)
