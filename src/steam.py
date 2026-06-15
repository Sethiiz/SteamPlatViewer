from __future__ import annotations

from dataclasses import dataclass

import aiohttp

BASE = "https://api.steampowered.com"

STATUS_NEVER      = "Nunca jogado"
STATUS_INCOMPLETE = "Incompleto"
STATUS_PLATINADO  = "Platinado"
STATUS_PRIVATE    = "Privado"


@dataclass
class OwnedGame:
    appid: int
    name: str
    playtime_forever: int


class SteamClient:
    def __init__(self, session: aiohttp.ClientSession, api_key: str) -> None:
        self._s = session
        self._key = api_key

    async def get_player_summary(self, steam_id: str) -> dict:
        async with self._s.get(
            f"{BASE}/ISteamUser/GetPlayerSummaries/v2/",
            params={"key": self._key, "steamids": steam_id},
        ) as r:
            data = await r.json()
        players = data.get("response", {}).get("players", [])
        return players[0] if players else {}

    async def resolve_vanity(self, vanity: str) -> str:
        async with self._s.get(
            f"{BASE}/ISteamUser/ResolveVanityURL/v1/",
            params={"key": self._key, "vanityurl": vanity},
        ) as r:
            data = (await r.json())["response"]
        if data.get("success") != 1:
            raise ValueError(f"Perfil não encontrado: {vanity}")
        return data["steamid"]

    async def get_owned_games(self, steam_id: str) -> list[OwnedGame]:
        async with self._s.get(
            f"{BASE}/IPlayerService/GetOwnedGames/v1/",
            params={
                "key": self._key,
                "steamid": steam_id,
                "include_appinfo": 1,
                "include_played_free_games": 1,
            },
        ) as r:
            games = (await r.json())["response"].get("games", [])
        return [
            OwnedGame(
                appid=g["appid"],
                name=g.get("name", f"AppID {g['appid']}"),
                playtime_forever=g.get("playtime_forever", 0),
            )
            for g in games
        ]

    async def get_achievement_count(self, appid: int) -> int:
        try:
            async with self._s.get(
                f"{BASE}/ISteamUserStats/GetSchemaForGame/v2/",
                params={"key": self._key, "appid": appid},
            ) as r:
                data = await r.json()
            return len(
                data.get("game", {})
                    .get("availableGameStats", {})
                    .get("achievements", [])
            )
        except Exception:
            return 0

    async def get_player_status(
        self, steam_id: str, appid: int, playtime: int, achievement_count: int
    ) -> str:
        if playtime == 0:
            return STATUS_NEVER
        if achievement_count == 0:
            return STATUS_INCOMPLETE
        try:
            async with self._s.get(
                f"{BASE}/ISteamUserStats/GetPlayerAchievements/v1/",
                params={"key": self._key, "steamid": steam_id, "appid": appid},
            ) as r:
                data = (await r.json()).get("playerstats", {})
            if not data.get("success"):
                if "not public" in data.get("error", "").lower():
                    return STATUS_PRIVATE
                return STATUS_INCOMPLETE
            achievements = data.get("achievements", [])
            if not achievements:
                return STATUS_INCOMPLETE
            if all(a["achieved"] == 1 for a in achievements):
                return STATUS_PLATINADO
            return STATUS_INCOMPLETE
        except Exception:
            return STATUS_INCOMPLETE
