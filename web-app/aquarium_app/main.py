from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api_admin import router as admin_router
from .api_auth import router as auth_router
from .api_device import router as device_router
from .api_public import router as public_router
from .config import Settings
from .mqtt_bridge import MqttBridge
from .store import Store


logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).with_name("static")


def create_app(settings: Settings | None = None) -> FastAPI:
    active_settings = settings or Settings.from_env()
    store = Store(active_settings)
    mqtt_bridge = MqttBridge(active_settings, store) if active_settings.mqtt_enabled else None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        generated_password, generated = store.initialize()
        if generated:
            logger.warning(
                "Initial admin password written to %s. Sign in and replace it immediately. Password: %s",
                active_settings.generated_admin_path,
                generated_password,
            )
        if mqtt_bridge:
            mqtt_bridge.start()
        store.cleanup(vacuum=False)

        async def maintenance_loop() -> None:
            cleanup_counter = 0
            while True:
                await asyncio.sleep(30)
                try:
                    await asyncio.to_thread(store.run_due_schedules)
                    cleanup_counter += 1
                    if cleanup_counter >= 2880:
                        await asyncio.to_thread(store.cleanup, None, vacuum=False)
                        cleanup_counter = 0
                except Exception:
                    logger.exception("Background maintenance failed")

        maintenance_task = asyncio.create_task(maintenance_loop())
        try:
            yield
        finally:
            maintenance_task.cancel()
            try:
                await maintenance_task
            except asyncio.CancelledError:
                pass
            if mqtt_bridge:
                mqtt_bridge.stop()

    app = FastAPI(
        title="Smart Aquarium Dashboard API",
        version=__version__,
        description="LAN-first ESP32 telemetry, control queue, forecasting, and administration API.",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )
    app.state.settings = active_settings
    app.state.store = store
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(active_settings.allowed_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-CSRF-Token"],
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'",
        )
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        return response

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    app.include_router(public_router)
    app.include_router(auth_router)
    app.include_router(device_router)
    app.include_router(admin_router)
    app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")

    @app.get("/", include_in_schema=False)
    def frontend() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app


app = create_app()
