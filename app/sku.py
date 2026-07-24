from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from app.models import Article


COLOR_ALIASES: dict[str, set[str]] = {
    "gold": {"gold", "голд", "золото", "золот", "золотой", "золотая", "g"},
    "grey": {"grey", "gray", "грей", "серый", "серая", "серое"},
    "black": {"black", "блэк", "блек", "черн", "чёрн", "черный", "чёрный", "черная", "чёрная"},
    "pink": {"pink", "пинк", "розов", "розовый", "розовая"},
    "orange": {"orange", "оранж", "оранжевый", "orahge"},
    "silver": {"silver", "серебр", "серебро", "сильвер"},
}

SIZE_ALIASES: dict[str, set[str]] = {
    "mini": {"mini", "мини"},
    "middle": {"middle", "мидл", "mid"},
    "max": {"max", "макс"},
    "ultra": {"ultra", "ультра"},
    "pro": {"pro", "про"},
}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = s.replace("ё", "е").replace("Ё", "е")
    s = s.replace("Х", "X").replace("х", "x")
    return s.lower()


def _color_key(token: str) -> str | None:
    t = _norm(token)
    for key, aliases in COLOR_ALIASES.items():
        if t == key or t in aliases:
            return key
        if len(t) >= 3 and any(t.startswith(a) or a.startswith(t) for a in aliases if len(a) >= 3):
            return key
    return None


def _size_key(token: str) -> str | None:
    t = _norm(token)
    for key, aliases in SIZE_ALIASES.items():
        if t in aliases or t == key:
            return key
    return None


def article_color(code: str) -> str | None:
    n = _norm(code)
    if "orahge" in n or "orang" in n:
        return "orange"
    for key in ("gold", "grey", "gray", "black", "pink", "silver"):
        if key in n:
            return "grey" if key == "gray" else key
    if "голд" in n or "золот" in n:
        return "gold"
    if "грей" in n or "сер" in n and "серебр" not in n:
        return "grey"
    if "черн" in n:
        return "black"
    if "розов" in n or "пинк" in n:
        return "pink"
    if "серебр" in n:
        return "silver"
    return None


def article_sizes(code: str) -> set[str]:
    n = _norm(code)
    found: set[str] = set()
    for key, aliases in SIZE_ALIASES.items():
        if any(a in n for a in aliases):
            found.add(key)
    return found


def article_prefix_num(code: str) -> str | None:
    m = re.match(r"^0*(\d{2,4})", (code or "").strip())
    return m.group(1).lstrip("0") or "0" if m else None


def _prefix_ok(code: str, wanted: list[str]) -> bool:
    if not wanted:
        return True
    pref = article_prefix_num(code)
    if pref is None:
        return False
    wanted_norm = {(w.lstrip("0") or "0") for w in wanted}
    return pref in wanted_norm


@dataclass
class SkuMatch:
    articles: list[str]
    ambiguous: bool
    message: str | None = None


def resolve_skus(text: str, catalog: list[Article]) -> SkuMatch:
    """Resolve free text like '042 голд' against seller vendor codes."""
    if not text or not catalog:
        return SkuMatch([], False, None)

    raw = text.strip()
    by_norm = {_norm(a.vendor_code): a.vendor_code for a in catalog if a.vendor_code}

    explicit = re.findall(r"\b\d{2,4}_[A-Za-zА-Яа-я0-9ХхX][A-Za-zА-Яа-я0-9_+\-/]*", raw)
    explicit_codes: list[str] = []
    for e in explicit:
        key = _norm(e)
        if key in by_norm:
            explicit_codes.append(by_norm[key])
            continue
        hits = [a.vendor_code for a in catalog if key in _norm(a.vendor_code)]
        explicit_codes.extend(hits)

    tokens = re.findall(r"[A-Za-zА-Яа-яЁё0-9]+", raw)
    prefixes: list[str] = []
    colors: list[str] = []
    sizes: list[str] = []
    for tok in tokens:
        if tok.isdigit() and 2 <= len(tok) <= 4:
            prefixes.append(tok)
            continue
        ck = _color_key(tok)
        if ck:
            colors.append(ck)
            continue
        sk = _size_key(tok)
        if sk:
            sizes.append(sk)

    if not prefixes and not explicit_codes:
        return SkuMatch([], False, None)

    candidates: list[Article] = []
    for art in catalog:
        if not art.active or not art.vendor_code:
            continue
        if prefixes and not _prefix_ok(art.vendor_code, prefixes):
            continue
        if not prefixes:
            # only explicit path
            continue
        col = article_color(art.vendor_code)
        if colors and col not in set(colors):
            continue
        art_sizes = article_sizes(art.vendor_code)
        if sizes and not (set(sizes) & art_sizes):
            continue
        candidates.append(art)

    candidates.sort(key=lambda a: (-(a.sales_90d or 0), -(a.stock or 0), a.vendor_code))

    if explicit_codes and not prefixes:
        uniq: list[str] = []
        seen: set[str] = set()
        for c in explicit_codes:
            if c not in seen:
                seen.add(c)
                uniq.append(c)
        return SkuMatch(uniq, False, None)

    if not candidates:
        return SkuMatch([], False, None)

    if len(candidates) == 1:
        return SkuMatch([candidates[0].vendor_code], False, None)

    if prefixes and colors:
        top, second = candidates[0], candidates[1]
        if (top.sales_90d or 0) >= 2 * max(second.sales_90d or 0, 1) and not sizes:
            return SkuMatch([top.vendor_code], False, None)
        if sizes:
            return SkuMatch([top.vendor_code], False, None)
        # same color+prefix but different models (middle vs not) — ask
        opts = "\n".join(f"• {a.vendor_code}" for a in candidates[:6])
        return SkuMatch(
            [a.vendor_code for a in candidates[:6]],
            True,
            f"Нашёл несколько под «{' '.join(prefixes)} {'/'.join(colors)}»:\n{opts}\n\nНапиши полный артикул или уточни (middle/mini).",
        )

    if prefixes and not colors:
        opts = "\n".join(f"• {a.vendor_code}" for a in candidates[:8])
        return SkuMatch(
            [a.vendor_code for a in candidates[:8]],
            True,
            f"Уточни цвет. Варианты для {prefixes[0]}:\n{opts}",
        )

    return SkuMatch([candidates[0].vendor_code], False, None)


def enrich_task_text(title: str, catalog: list[Article]) -> tuple[str, str, str | None]:
    """Returns (title, articles_csv, clarify_message)."""
    match = resolve_skus(title, catalog)
    if match.ambiguous:
        return title, "", match.message
    if not match.articles:
        return title, "", None
    articles = ", ".join(match.articles)
    title_out = title.strip()
    for code in match.articles:
        if code not in title_out:
            title_out = f"{title_out} [{code}]"
    return title_out, articles, None
