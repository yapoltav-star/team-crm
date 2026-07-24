# team-crm

CRM команды: канбан по проектам на сайте + Telegram-бот (уведомления и контроль «сделано»).

## Стек

- **API + Web:** FastAPI (отдаёт канбан и REST)
- **Bot:** aiogram (в том же процессе)
- **DB:** SQLite локально, **Postgres на Railway** (`DATABASE_URL`)

## Локально

```bash
cd ~/Projects/team-crm
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# заполни TELEGRAM_BOT_TOKEN и OWNER_TELEGRAM_ID
uvicorn app.main:app --reload --port 8000
```

Открой http://127.0.0.1:8000

## Railway

1. Залей репозиторий на GitHub
2. [railway.app](https://railway.app) → New Project → Deploy from GitHub → выбери `team-crm`
3. **Обязательно:** Add Plugin / Database → **PostgreSQL**
4. В сервисе `team-crm` → Variables → Connect / Reference → `DATABASE_URL` из Postgres  
   (без этого менеджеры и задачи стираются при каждом деплое — SQLite в контейнере)
5. Другие Variables:
   - `TELEGRAM_BOT_TOKEN`
   - `OWNER_TELEGRAM_ID`
   - `TZ=Europe/Moscow`
   - `ESCALATE_TIME=20:00`
   - `WEB_PASSWORD` (пароль к сайту)
6. Deploy. Settings → Networking → Generate Domain

Проверка: открой `/health` — должно быть `"db":"postgres","persistent":true`.

Бот и сайт крутятся одним сервисом.

## Автозадачи: наш склад (WB Dashboard)

Пока смотрим только раздел **«Наш склад»** (не склады WB).

Правило: остаток семьи на нашем складе ≤ `STOCK_OWN_MAX_STOCK` **и** по артикулу
есть продажи (заказы/выкупы) → задача в CRM + Telegram.

Variables:
- `WB_DASHBOARD_URL`
- `STOCK_WATCH_ENABLED=true`
- `STOCK_OWN_MAX_STOCK=0` — алерт при пустом складе (поставь `2`, если нужно «мало»)
- `STOCK_MIN_ORDERS=5` / `STOCK_REQUIRE_BUYOUTS=true` — фильтр «есть продажи»
- `STOCK_MAX_TASKS=10`
- `STOCK_ASSIGNEE_TELEGRAM_ID` — кому (0 = владелец)

Ручной запуск: `POST /api/stock-watch/run` (с `x-crm-password` если задан).

Склады WB по регионам — позже отдельной задачей.
