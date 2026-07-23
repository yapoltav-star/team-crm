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
3. Add Plugin → **PostgreSQL**
4. Variables:
   - `TELEGRAM_BOT_TOKEN`
   - `OWNER_TELEGRAM_ID`
   - `TZ=Europe/Moscow`
   - `ESCALATE_TIME=20:00`
   - `DATABASE_URL` подтянется из Postgres автоматически (если линк сервиса)
5. Deploy. В Settings → Networking → Generate Domain

Бот и сайт крутятся одним сервисом.
