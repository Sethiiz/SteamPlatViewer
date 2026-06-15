from __future__ import annotations

import asyncio
import re
import unicodedata
from dataclasses import dataclass

from howlongtobeatpy import HowLongToBeat

RATE_DELAY = 0.35


@dataclass
class HLTBResult:
    hours: float
    url: str


def _light_clean(name: str) -> str:
    cleaned = re.sub(r"[™®©℠]", "", name)
    return re.sub(r"\s+", " ", cleaned).strip()


def _normalize(name: str) -> str:
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_name = nfkd.encode("ascii", "ignore").decode("ascii")
    no_special = re.sub(r"[^a-zA-Z0-9 ]", " ", ascii_name)
    return re.sub(r"\s+", " ", no_special).strip()


async def _search_once(name: str) -> HLTBResult | None:
    loop = asyncio.get_event_loop()
    try:
        results = await loop.run_in_executor(None, lambda: HowLongToBeat().search(name))
    except Exception:
        return None
    if not results:
        return None
    exact = next((r for r in results if r.game_name.lower() == name.lower()), None)
    best = exact or max(results, key=lambda r: r.similarity)
    if not exact and best.similarity < 0.5:
        return None
    hours = best.completionist
    if not hours or hours <= 0:
        hours = best.all_styles
    if not hours or hours <= 0:
        return None
    return HLTBResult(hours=hours, url=best.game_web_link)


async def search(name: str) -> HLTBResult | None:
    if result := await _search_once(name):
        return result

    light = _light_clean(name)
    if light != name:
        await asyncio.sleep(RATE_DELAY)
        if result := await _search_once(light):
            return result

    full = _normalize(name)
    if full and full != light and full != name:
        await asyncio.sleep(RATE_DELAY)
        if result := await _search_once(full):
            return result

    return None
