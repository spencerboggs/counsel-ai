"""AI Counsel FastAPI application entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes import api_router
from backend.config.settings import get_settings
from backend.storage.database import Database


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    db_path = Path(settings.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    database = Database(db_path)
    await database.connect()
    await database.migrate()
    app.state.db = database
    app.state.settings = settings
    app.state.background_tasks = set()
    # Startup reconcile snapshot (does not auto-trade).
    try:
        from backend.autopilot.wake import wake_reconcile
        from backend.autopilot.state import AutopilotStore

        store = AutopilotStore(database)
        prior = await store.get()
        wake = await wake_reconcile(
            database,
            asleep_since=prior.get("asleep_since") or prior.get("stopped_at"),
        )
        app.state.startup_wake = wake
    except Exception as exc:
        app.state.startup_wake = {"error": str(exc)}
    try:
        yield
    finally:
        try:
            from backend.autopilot.loop import is_loop_running, stop_loop

            if is_loop_running():
                await stop_loop(database)
        except Exception:
            pass
        await database.close()


app = FastAPI(
    title="AI Counsel",
    version="0.1.0",
    description="Local research backend for AI Counsel",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:1420",
        "http://localhost:1420",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "tauri://localhost",
        "https://tauri.localhost",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
