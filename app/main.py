from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import router as api_router
from app.bot import build_dispatcher, materialize_and_notify
from app.config import get_settings
from app.db import SessionLocal, init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("team-crm")

WEB_ROOT = Path(__file__).resolve().parent.parent / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if settings.db_backend == "sqlite":
        msg = (
            "DATABASE_URL не задан — используется SQLite. "
            "На Railway данные (менеджеры, задачи) ПРОПАДУТ при каждом деплое. "
            "Добавь Postgres и переменную DATABASE_URL."
        )
        if settings.on_railway:
            logger.error(msg)
            raise RuntimeError(msg)
        logger.warning(msg)
    else:
        logger.info("DB backend: %s", settings.db_backend)
    await init_db()
    scheduler = AsyncIOScheduler(timezone=settings.tz_name)
    bot = None
    poll_task = None

    dp = None
    if settings.bot_enabled:
        bot, dp = build_dispatcher(settings, SessionLocal)

        async def tick() -> None:
            await materialize_and_notify(SessionLocal, bot, settings)

        scheduler.add_job(tick, "interval", minutes=1, id="crm_tick", replace_existing=True, max_instances=1)
        scheduler.start()
        await tick()
        # снять webhook и чужой polling-хвост перед стартом
        try:
            await bot.delete_webhook(drop_pending_updates=False)
        except Exception:  # noqa: BLE001
            logger.exception("delete_webhook failed")
        poll_task = asyncio.create_task(
            dp.start_polling(bot, handle_signals=False, allowed_updates=dp.resolve_used_update_types())
        )
        logger.info("Telegram bot + scheduler started")
    else:
        logger.warning("Bot disabled: set TELEGRAM_BOT_TOKEN and OWNER_TELEGRAM_ID")

    app.state.bot = bot
    app.state.scheduler = scheduler
    app.state.dp = dp
    yield

    if scheduler.running:
        scheduler.shutdown(wait=False)
    if dp is not None:
        try:
            await dp.stop_polling()
        except Exception:  # noqa: BLE001
            logger.exception("stop_polling failed")
    if poll_task:
        poll_task.cancel()
        try:
            await poll_task
        except asyncio.CancelledError:
            pass
    if bot:
        await bot.session.close()


app = FastAPI(title="team-crm", lifespan=lifespan)
app.include_router(api_router)


@app.middleware("http")
async def simple_password(request: Request, call_next):
    settings = get_settings()
    if settings.web_password and request.url.path.startswith("/api"):
        pwd = request.headers.get("x-crm-password") or request.query_params.get("password")
        if pwd != settings.web_password:
            # HTTPException in middleware becomes 500 — return Response explicitly
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return await call_next(request)


@app.get("/health")
async def health() -> dict:
    settings = get_settings()
    return {
        "ok": True,
        "build": "notify-all-2026-07-24",
        "db": settings.db_backend,
        "persistent": settings.db_backend == "postgres",
    }


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB_ROOT / "index.html")


@app.get("/static/{file_path:path}")
async def static_file(file_path: str) -> FileResponse:
    """Явная раздача web/* — надёжнее, чем только StaticFiles mount."""
    target = (WEB_ROOT / file_path).resolve()
    if not str(target).startswith(str(WEB_ROOT.resolve())) or not target.is_file():
        return JSONResponse({"detail": "Not found"}, status_code=404)
    return FileResponse(target)


if WEB_ROOT.exists():
    # fallback mount (если route выше не сматчится в каких-то окружениях)
    app.mount("/assets", StaticFiles(directory=WEB_ROOT), name="assets")