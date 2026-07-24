from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Article

logger = logging.getLogger(__name__)

SEED_PATH = Path(__file__).resolve().parent / "seed" / "articles.json"


async def load_catalog(session: AsyncSession, *, active_only: bool = True) -> list[Article]:
    q = select(Article).order_by(Article.sales_90d.desc(), Article.vendor_code)
    if active_only:
        q = q.where(Article.active.is_(True))
    return list(await session.scalars(q))


async def seed_articles_from_file(session: AsyncSession, path: Path | None = None) -> int:
    seed = path or SEED_PATH
    if not seed.exists():
        logger.warning("articles seed missing: %s", seed)
        return 0
    raw = json.loads(seed.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        return 0

    existing = {
        a.vendor_code: a
        for a in (await session.scalars(select(Article))).all()
    }
    now = datetime.utcnow()
    upserted = 0
    seen: set[str] = set()
    for row in raw:
        code = str(row.get("vendorCode") or "").strip()
        if not code or code in seen:
            continue
        seen.add(code)
        nm = row.get("nmId")
        stock = int(row.get("stock") or 0)
        sales = int(row.get("sales90d") or 0)
        art = existing.get(code)
        if art:
            art.nm_id = int(nm) if nm is not None else art.nm_id
            art.stock = stock
            art.sales_90d = sales
            art.active = True
            art.updated_at = now
        else:
            session.add(
                Article(
                    vendor_code=code,
                    nm_id=int(nm) if nm is not None else None,
                    stock=stock,
                    sales_90d=sales,
                    active=True,
                    updated_at=now,
                )
            )
        upserted += 1
    await session.commit()
    logger.info("articles seeded: %s from %s", upserted, seed.name)
    return upserted
