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
    # менеджер пишет /start или текст — сам появляется в команде
    allow_self_join: bool = Field(default=True, alias="ALLOW_SELF_JOIN")

    @field_validator(
        "telegram_proxy",
        "database_url",
        "web_password",
        "openai_api_key",
        "openai_base_url",
        mode="before",
    )
    @classmethod
    def empty_str(cls, value: object) -> object:
        if value is None:
            return ""
        return value

    @field_validator("allow_self_join", mode="before")
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
    def bot_enabled(self) -> bool:
        return bool(self.telegram_bot_token and self.owner_telegram_id)

    @property
    def nlp_enabled(self) -> bool:
        return bool(str(self.openai_api_key).strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
