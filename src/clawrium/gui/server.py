"""FastAPI server for Clawrium GUI.

Serves the static Next.js frontend and provides REST API
endpoints for fleet management, token tracking, and chat.
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from clawrium.gui.routes import agents, fleet, topology, providers, settings, usage

app = FastAPI(
    title="Clawrium GUI",
    description="Local web dashboard for AI assistant fleet management",
    version="0.1.0",
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

    @app.get("/{path:path}")
    async def serve_frontend(request: Request, path: str) -> Response:
        """Serve static HTML pages for frontend routes."""
        # Try exact file first (e.g. favicon.ico)
        exact = frontend_dir / path
        if exact.is_file():
            return FileResponse(exact)

        # Try path + .html (e.g. /topology -> topology.html)
        html_file = frontend_dir / f"{path}.html"
        if html_file.is_file():
            return FileResponse(html_file)

        # Try path/index.html (for trailing slash dirs)
        index_file = frontend_dir / path / "index.html"
        if index_file.is_file():
            return FileResponse(index_file)

        # Fallback to index.html for client-side routing
        return FileResponse(frontend_dir / "index.html")


# Mount frontend static files (noop if not built yet)
mount_frontend(app)
