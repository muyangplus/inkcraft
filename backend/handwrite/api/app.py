"""FastAPI application factory with lifespan, CORS, error envelopes, and SPA static serving."""

from __future__ import annotations

from contextlib import asynccontextmanager
import logging
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from handwrite import CONTRACT_VERSION, __version__
from handwrite.api.routes import (
    backgrounds,
    documents,
    font_builder,
    health,
    jobs,
    layouts,
    machine,
    tasks,
    writers,
)
from handwrite.api.state import ApiError, AppContext
from handwrite.api.ws import router as ws_router
from handwrite.config import Settings
from handwrite.gcode.optimizer import WorkspaceBoundsError
from handwrite.grbl.controller import MachineStateError

logger = logging.getLogger(__name__)


def _error_response(
    status_code: int,
    code: str,
    message: str,
    details: dict | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details,
            }
        },
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the handwrite FastAPI application."""
    cfg = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        ctx = AppContext(cfg)
        app.state.ctx = ctx
        app.state.settings = ctx.settings
        app.state.db = ctx.db
        app.state.event_bus = ctx.event_bus
        app.state.tasks = ctx.tasks
        app.state.writers = ctx.writers
        app.state.machine = ctx.machine
        ctx.startup()
        try:
            yield
        finally:
            ctx.shutdown()

    app = FastAPI(
        title="Handwrite GRBL Writing Arm Host API",
        version=__version__,
        description=f"Standalone AI Multi-Writer Handwriting & GRBL Writing Arm Host System (Contract v{CONTRACT_VERSION})",
        lifespan=lifespan,
    )

    # CORS for local browser dev (Vite dev server & direct localhost)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[
            "X-Page-Width-Mm",
            "X-Page-Height-Mm",
            "X-Bbox",
            "X-Stroke-Count",
            "X-Seg-Count",
            "Content-Disposition",
        ],
    )

    # Global unified error envelope handlers
    @app.exception_handler(ApiError)
    async def _handle_api_error(_request: Request, exc: ApiError) -> JSONResponse:
        return _error_response(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(WorkspaceBoundsError)
    async def _handle_bounds_error(
        _request: Request, exc: WorkspaceBoundsError
    ) -> JSONResponse:
        return _error_response(
            422,
            "OUT_OF_BOUNDS",
            str(exc),
            {"violations": exc.violations},
        )

    @app.exception_handler(MachineStateError)
    async def _handle_machine_state_error(
        _request: Request, exc: MachineStateError
    ) -> JSONResponse:
        return _error_response(409, "INVALID_MACHINE_STATE", str(exc))

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return _error_response(
            422,
            "VALIDATION_ERROR",
            "请求参数校验失败",
            {"errors": exc.errors()},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_error(
        _request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        return _error_response(
            exc.status_code,
            f"HTTP_{exc.status_code}",
            str(exc.detail),
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected_error(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled server exception: %s", exc)
        return _error_response(500, "INTERNAL_ERROR", str(exc))

    # Mount REST v1 routers
    api_prefix = "/api/v1"
    app.include_router(health.router, prefix=api_prefix, tags=["system"])
    app.include_router(tasks.router, prefix=api_prefix, tags=["tasks"])
    app.include_router(writers.router, prefix=api_prefix, tags=["writers"])
    app.include_router(font_builder.router, prefix=api_prefix, tags=["font-builder"])
    app.include_router(backgrounds.router, prefix=api_prefix, tags=["backgrounds"])
    app.include_router(documents.router, prefix=api_prefix, tags=["documents"])
    app.include_router(layouts.router, prefix=api_prefix, tags=["layouts"])
    app.include_router(machine.router, prefix=api_prefix, tags=["machine"])
    app.include_router(jobs.router, prefix=api_prefix, tags=["jobs"])

    # Mount WebSocket endpoint
    app.include_router(ws_router)

    # Serve built frontend SPA when frontend/dist exists
    dist_dir = cfg.FRONTEND_DIST_DIR
    if dist_dir.is_dir() and (dist_dir / "index.html").is_file():
        assets_dir = dist_dir / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def _serve_spa(full_path: str):
            if full_path.startswith("api/") or full_path.startswith("ws/"):
                return _error_response(404, "NOT_FOUND", f"Route '/{full_path}' not found")
            dist_root = dist_dir.resolve()
            candidate = (dist_root / full_path).resolve()
            if (
                full_path
                and candidate.is_file()
                and candidate.is_relative_to(dist_root)
            ):
                return FileResponse(candidate)
            return FileResponse(dist_dir / "index.html")

    return app
