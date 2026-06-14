from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

PROGRESS_PATH = "progress.json"


@dataclass
class NoHLTBGame:
    appid: int
    name: str
    achievements: int


@dataclass
class Progress:
    steam_id: str = ""
    processed: list[int] = field(default_factory=list)
    no_hltb: list[NoHLTBGame] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._set: set[int] = set(self.processed)

    @classmethod
    def load(cls) -> Progress:
        if os.path.exists(PROGRESS_PATH):
            try:
                with open(PROGRESS_PATH, encoding="utf-8") as f:
                    data = json.load(f)
                return cls(
                    steam_id=data.get("steam_id", ""),
                    processed=data.get("processed", []),
                    no_hltb=[NoHLTBGame(**g) for g in data.get("no_hltb", [])],
                )
            except Exception:
                pass
        return cls()

    def save(self) -> None:
        with open(PROGRESS_PATH, "w", encoding="utf-8") as f:
            json.dump({
                "steam_id": self.steam_id,
                "processed": self.processed,
                "no_hltb": [{"appid": g.appid, "name": g.name, "achievements": g.achievements}
                             for g in self.no_hltb],
            }, f, ensure_ascii=False, indent=2)

    def is_processed(self, appid: int) -> bool:
        return appid in self._set

    def mark_processed(self, appid: int) -> None:
        if appid not in self._set:
            self._set.add(appid)
            self.processed.append(appid)
        self.save()

    def add_no_hltb(self, game: NoHLTBGame) -> None:
        self.no_hltb.append(game)
        self.save()

    def clear(self) -> None:
        self.steam_id = ""
        self.processed.clear()
        self.no_hltb.clear()
        self._set.clear()
        if os.path.exists(PROGRESS_PATH):
            os.remove(PROGRESS_PATH)
