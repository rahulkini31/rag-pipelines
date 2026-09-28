"""FastAPI entry point for the Hybrid RAG management cockpit."""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .events import init_log_capture
from .router_auth import router as auth_router
from .router_config import router as config_router
from .router_documents import router as documents_router
from .router_evals import router as evals_router
from .router_telemetry import router as telemetry_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="Hybrid RAG Document Management System",
        description="Next.js-backed management cockpit for the Hybrid RAG pipeline.",
        version="0.1.0",
    )

    frontend_origin = os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[frontend_origin],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth_router)
    app.include_router(config_router)
    app.include_router(documents_router)
    app.include_router(telemetry_router)
    app.include_router(evals_router)

    @app.get("/health")
    async def health_check() -> dict:
        return {"status": "ok"}

    return app


# Initialize log capture on startup
init_log_capture()
app = create_app()
