from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.api import router as api_router
from app.auth import password_ok, request_password
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
    if settings.on_railway and not str(settings.web_password or "").strip():
        msg = (
            "WEB_PASSWORD не задан. На Railway сайт будет открыт всем. "
            "Задай WEB_PASSWORD в Variables."
        )
        logger.error(msg)
        raise RuntimeError(msg)
    if not str(settings.web_password or "").strip():
        logger.warning("WEB_PASSWORD пуст — веб без пароля (только для локалки)")
    await init_db()
    scheduler = AsyncIOScheduler(timezone=settings.tz_name)
    bot = None
    poll_task = None
    dp = None

    if settings.bot_enabled:
        bot, dp = build_dispatcher(settings, SessionLocal)

        async def tick() -> None:
            await materialize_and_notify(SessionLocal, bot, settings)

        scheduler.add_job(
            tick, "interval", minutes=1, id="crm_tick", replace_existing=True, max_instances=1
        )
        # снять webhook и чужой polling-хвост перед стартом
        try:
            await bot.delete_webhook(drop_pending_updates=False)
        except Exception:  # noqa: BLE001
            logger.exception("delete_webhook failed")
        poll_task = asyncio.create_task(
            dp.start_polling(bot, handle_signals=False, allowed_updates=dp.resolve_used_update_types())
        )
        logger.info("Telegram bot started")
    else:
        logger.warning("Bot disabled: set TELEGRAM_BOT_TOKEN and OWNER_TELEGRAM_ID")

    app.state.bot = bot
    app.state.scheduler = scheduler
    app.state.dp = dp
    app.state.last_stock_watch = None

    if settings.stock_watch_enabled and settings.wb_dashboard_url:
        from apscheduler.triggers.cron import CronTrigger

        from app.stock_watch import run_stock_watch

        async def stock_tick() -> None:
            result = await run_stock_watch(
                session_factory=SessionLocal,
                settings=settings,
                bot=getattr(app.state, "bot", None),
            )
            app.state.last_stock_watch = result
            logger.info("stock_watch: %s", result)

        raw_time = (settings.stock_watch_time or "09:00").strip()
        try:
            hh, mm = [int(x) for x in raw_time.split(":")[:2]]
        except Exception:  # noqa: BLE001
            hh, mm = 9, 0
        days = (settings.stock_watch_days or "mon,wed,fri").strip() or "mon,wed,fri"
        scheduler.add_job(
            stock_tick,
            CronTrigger(
                day_of_week=days,
                hour=hh,
                minute=mm,
                timezone=settings.tz_name,
            ),
            id="stock_watch",
            replace_existing=True,
            max_instances=1,
        )
        logger.info(
            "Stock watch enabled → %s on %s at %02d:%02d (%s), cooldown %sd",
            settings.wb_dashboard_url,
            days,
            hh,
            mm,
            settings.tz_name,
            settings.stock_cooldown_days,
        )

    scheduler.start()
    if settings.bot_enabled and bot is not None:
        await materialize_and_notify(SessionLocal, bot, settings)

    from app.archive import archive_old_done_tasks

    async def archive_tick() -> None:
        result = await archive_old_done_tasks(SessionLocal)
        logger.info("archive_tick: %s", result)

    scheduler.add_job(
        archive_tick,
        "cron",
        hour=3,
        minute=15,
        timezone=settings.tz_name,
        id="archive_done",
        replace_existing=True,
        max_instances=1,
    )
    try:
        await archive_old_done_tasks(SessionLocal)
    except Exception:  # noqa: BLE001
        logger.exception("archive first run failed")

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

PUBLIC_PATHS = {
    "/health",
    "/login",
    "/api/auth/login",
}


class LoginIn(BaseModel):
    password: str


@app.middleware("http")
async def site_password_gate(request: Request, call_next):
    settings = get_settings()
    path = request.url.path
    if path in PUBLIC_PATHS:
        return await call_next(request)
    if not str(settings.web_password or "").strip():
        return await call_next(request)

    if password_ok(settings, request_password(request)):
        return await call_next(request)

    accept = (request.headers.get("accept") or "").lower()
    is_api = path.startswith("/api")
    if not is_api and ("text/html" in accept or path == "/" or path.startswith("/static")):
        # для статики после редиректа на login — просто 401/redirect
        if path.startswith("/static"):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        return RedirectResponse(url="/login", status_code=302)
    return JSONResponse({"detail": "Unauthorized"}, status_code=401)


@app.post("/api/auth/login")
async def auth_login(body: LoginIn):
    settings = get_settings()
    if not password_ok(settings, body.password):
        return JSONResponse({"detail": "Неверный пароль"}, status_code=401)
    resp = JSONResponse({"ok": True})
    resp.set_cookie(
        key="crm_password",
        value=body.password.strip(),
        httponly=True,
        samesite="lax",
        secure=bool(settings.on_railway),
        max_age=60 * 60 * 24 * 30,
        path="/",
    )
    return resp


@app.post("/api/auth/logout")
async def auth_logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("crm_password", path="/")
    return resp


@app.get("/health")
async def health() -> dict:
    settings = get_settings()
    return {
        "ok": True,
        "build": "archive-scroll-2026-07-24",
        "db": settings.db_backend,
        "persistent": settings.db_backend == "postgres",
        "auth": bool(str(settings.web_password or "").strip()),
    }


@app.get("/login")
async def login_page() -> FileResponse:
    return FileResponse(WEB_ROOT / "login.html")


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