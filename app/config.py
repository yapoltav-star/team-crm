from __future__ import annotations

from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    owner_telegram_id: int = Field(default=0, alias="OWNER_TELEGRAM_ID")
    tz_name: str = Field(default="Europe/Moscow", alias="TZ")
    escalate_time: str = Field(default="20:00", alias="ESCALATE_TIME")
    telegram_proxy: str | None = Field(default=None, alias="TELEGRAM_PROXY")
    database_url: str = Field(default="", alias="DATABASE_URL")
    web_password: str = Field(default="", alias="WEB_PASSWORD")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4.1-mini", alias="OPENAI_MODEL")
    openai_base_url: str = Field(default="", alias="OPENAI_BASE_URL")
    # устаревший авто-вход без одобрения (по умолчанию выкл — заявка владельцу)
    allow_self_join: bool = Field(default=False, alias="ALLOW_SELF_JOIN")

    # Связка с WB Dashboard — пока только «Наш склад»
    wb_dashboard_url: str = Field(
        default="https://wb-dashboard-production-baf4.up.railway.app",
        alias="WB_DASHBOARD_URL",
    )
    stock_watch_enabled: bool = Field(default=True, alias="STOCK_WATCH_ENABLED")
    # пн,ср,пт — дни проверки (cron day_of_week)
    stock_watch_days: str = Field(default="mon,wed,fri", alias="STOCK_WATCH_DAYS")
    stock_watch_time: str = Field(default="09:00", alias="STOCK_WATCH_TIME")
    # не создавать повторно по тому же артикулу/семье N дней (даже если старую закрыли)
    stock_cooldown_days: int = Field(default=7, alias="STOCK_COOLDOWN_DAYS")
    # алерт если остаток семьи на нашем складе ≤ этого числа (0 = пусто)
    stock_own_max_stock: int = Field(default=0, alias="STOCK_OWN_MAX_STOCK")
    # минимум заказов за период — без продаж задачи не создаём
    stock_min_orders: int = Field(default=5, alias="STOCK_MIN_ORDERS")
    # требовать хотя бы 1 выкуп
    stock_require_buyouts: bool = Field(default=True, alias="STOCK_REQUIRE_BUYOUTS")
    stock_max_tasks: int = Field(default=10, alias="STOCK_MAX_TASKS")
    # кому ставить задачи; 0 = владельцу
    stock_assignee_telegram_id: int = Field(default=0, alias="STOCK_ASSIGNEE_TELEGRAM_ID")

    @field_validator(
        "telegram_proxy",
        "database_url",
        "web_password",
        "openai_api_key",
        "openai_base_url",
        "wb_dashboard_url",
        "stock_watch_days",
        "stock_watch_time",
        mode="before",
    )
    @classmethod
    def empty_str(cls, value: object) -> object:
        if value is None:
            return ""
        return value

    @field_validator(
        "allow_self_join",
        "stock_watch_enabled",
        "stock_require_buyouts",
        mode="before",
    )
    @classmethod
    def boolish(cls, value: object) -> object:
        if isinstance(value, str):
            v = value.strip().lower()
            if v in {"0", "false", "no", "off", ""}:
                return False
            if v in {"1", "true", "yes", "on"}:
                return True
        return value

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.tz_name)

    @property
    def sqlalchemy_url(self) -> str:
        url = (self.database_url or "").strip()
        if not url:
            return "sqlite+aiosqlite:///./data/crm.db"
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url

    @property
    def db_backend(self) -> str:
        url = self.sqlalchemy_url
        if url.startswith("sqlite"):
            return "sqlite"
        if "postgres" in url:
            return "postgres"
        return "other"

    @property
    def on_railway(self) -> bool:
        import os

        return bool(os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("RAILWAY_PROJECT_ID"))

    @property
    def bot_enabled(self) -> bool:
        return bool(self.telegram_bot_token and self.owner_telegram_id)

    @property
    def nlp_enabled(self) -> bool:
        return bool(str(self.openai_api_key).strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
