from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.dashboard import router as dashboard_router
from app.api.admin_console import router as admin_console_router
from app.api.history import router as history_router
from app.api.images import router as images_router
from app.api.management import router as management_router
from app.api.metrics import router as metrics_router
from app.api.openai_compatible import router as openai_router
from app.api.routes import router as system_router
from app.api.routing import router as routing_router
from app.auth.router import router as auth_router
from app.config.settings import settings
from app.security.guards import csrf_is_valid


# ============================================================
# Paths
# ============================================================

BASE_DIR = Path(__file__).resolve().parents[2]

FRONTEND_DIR = BASE_DIR / "frontend"


# ============================================================
# Application factory
# ============================================================

def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.

    API layout:

        /health
        /ready
        /cache/stats
        /cache
        /lifecycle

        /metrics

        /v1/chat/completions

        /api/auth/oauth/{provider}/start
        /api/auth/oauth/{provider}/callback
        /api/auth/me
        /api/auth/logout

        /api/dashboard
        /api/cache
        /api/cache/entries
        /api/providers
        /api/requests
        /api/metrics
        /api/system
        /api/settings
        /api/playground

        /api/history
        /api/history/{request_id}

        /api/routing/preview
        /api/routing/models
    """

    app = FastAPI(
        title="AI Semantic Cache Gateway",
        version="2.0.0",
        description=(
            "OpenAI-compatible AI gateway with semantic "
            "cache, automatic model routing, providers, "
            "history, authentication and observability."
        ),
    )

    # ========================================================
    # CORS
    # ========================================================

    cors_origins = settings.cors_origins
    if not cors_origins:
        cors_origins = ["http://127.0.0.1:8000", "http://localhost:8000"]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Accept", "Authorization", "Content-Type", "X-CSRF-Token"],
    )

    @app.middleware("http")
    async def prevent_stale_frontend(
        request: Request,
        call_next,
    ):
        if not csrf_is_valid(request):
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=403,
                content={"detail": "CSRF validation failed"},
            )
        response = await call_next(request)
        path = request.url.path
        if path == "/" or path.startswith(("/pages/", "/js/", "/css/")):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if settings.production_mode and settings.effective_cookie_secure:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response

    # ========================================================
    # Core system routes
    #
    # routes.py already owns:
    #
    #   /health
    #   /ready
    #   /cache/stats
    #   DELETE /cache
    #   /lifecycle
    # ========================================================

    app.include_router(
        system_router
    )

    # ========================================================
    # Prometheus / metrics
    # ========================================================

    app.include_router(
        metrics_router
    )

    # ========================================================
    # OpenAI-compatible API
    #
    #   POST /v1/chat/completions
    # ========================================================

    app.include_router(
        openai_router
    )

    # ========================================================
    # Authentication API
    #
    #   GET  /api/auth/oauth/{provider}/start
    #   GET  /api/auth/oauth/{provider}/callback
    #   GET  /api/auth/me
    #   POST /api/auth/logout
    # ========================================================

    app.include_router(
        auth_router
    )

    # ========================================================
    # Dashboard / management API
    #
    # dashboard.py already contains:
    #
    #   /api/dashboard
    #   /api/cache
    #   /api/cache/entries
    #   /api/providers
    #   /api/requests
    #   /api/metrics
    #   /api/system
    #   /api/settings
    #   /api/playground
    # ========================================================

    app.include_router(
        dashboard_router
    )

    app.include_router(
        management_router
    )

    app.include_router(
        admin_console_router
    )

    # ========================================================
    # History API
    #
    #   /api/history
    #   /api/history/{request_id}
    # ========================================================

    app.include_router(
        history_router
    )

    app.include_router(
        images_router
    )

    # ========================================================
    # Automatic model routing API
    #
    #   POST /api/routing/preview
    #   GET  /api/routing/models
    # ========================================================

    app.include_router(
        routing_router
    )

    # ========================================================
    # Application status
    # ========================================================

    @app.get(
        "/api/status",
        tags=["system"],
    )
    def api_status() -> dict[str, str]:
        return {
            "name": "AI Semantic Cache Gateway",
            "version": "2.0.0",
            "status": "running",
        }

    # ========================================================
    # Frontend
    #
    # StaticFiles is mounted at "/" so the frontend remains
    # directly accessible:
    #
    #   /
    #   /pages/cache.html
    #   /pages/playground.html
    #   ...
    #
    # API routes are registered BEFORE this mount so they
    # remain handled by FastAPI instead of being treated as
    # static files.
    # ========================================================

    if FRONTEND_DIR.exists():

        app.mount(
            "/",
            StaticFiles(
                directory=str(
                    FRONTEND_DIR
                ),
                html=True,
            ),
            name="frontend",
        )

    return app


# ============================================================
# Application instance
# ============================================================

app = create_app()
