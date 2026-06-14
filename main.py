from __future__ import annotations

import asyncio
import os
import re
import sys

import aiohttp
from dotenv import load_dotenv

from src.excel import ExcelWriter, Game
from src.hltb import search as hltb_search
from src.progress import NoHLTBGame, Progress
from src.steam import SteamClient

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

STEAM_SEM  = 25
HLTB_SEM   = 5


def _resolve_steam_input(raw: str) -> str | None:
    raw = raw.strip()
    # SteamID64 direto (17 dígitos numéricos)
    if re.fullmatch(r"\d{17}", raw):
        return raw
    # URL tipo steamcommunity.com/profiles/76561198XXXXXXXXX
    m = re.search(r"/profiles/(\d{17})", raw)
    if m:
        return m.group(1)
    # URL tipo steamcommunity.com/id/VANITY
    m = re.search(r"/id/([^/?\s]+)", raw)
    if m:
        return m.group(1)  # retorna vanity; resolvemos depois
    # Qualquer outra string não-vazia = vanity
    if raw:
        return raw
    return None


async def _ensure_steam_id(raw: str, client: SteamClient) -> str:
    if re.fullmatch(r"\d{17}", raw):
        return raw
    return await client.resolve_vanity(raw)


async def run_processing(
    steam_id: str,
    progress: Progress,
    excel: ExcelWriter,
    client: SteamClient,
) -> None:
    games = await client.get_owned_games(steam_id)
    pending = [g for g in games if not progress.is_processed(g.appid)]

    if not pending:
        print("Todos os jogos já foram processados.")
        return

    total = len(pending)
    print(f"\n{total} jogos a processar.\n")

    steam_sem = asyncio.Semaphore(STEAM_SEM)
    hltb_sem  = asyncio.Semaphore(HLTB_SEM)
    write_lock = asyncio.Lock()

    async def process_one(game, idx: int) -> None:
        async def fetch_ach() -> int:
            async with steam_sem:
                return await client.get_achievement_count(game.appid)

        async def fetch_hltb():
            async with hltb_sem:
                return await hltb_search(game.name)

        ach_count, hltb = await asyncio.gather(fetch_ach(), fetch_hltb())

        async with steam_sem:
            status = await client.get_player_status(
                steam_id, game.appid, game.playtime_forever, ach_count
            )

        if ach_count == 0:
            print(f"[{idx}/{total}] {game.name} — sem conquistas")
            async with write_lock:
                progress.mark_processed(game.appid)
            return

        if hltb is None:
            print(f"[{idx}/{total}] {game.name} — {ach_count} conquistas — sem HLTB")
            async with write_lock:
                progress.add_no_hltb(NoHLTBGame(game.appid, game.name, ach_count))
                progress.mark_processed(game.appid)
            return

        print(f"[{idx}/{total}] {game.name} — {ach_count} conquistas — {hltb.hours}h (HLTB) — {status} ✓")
        entry = Game(
            name=game.name,
            status=status,
            link_hltb=hltb.url,
            achievements=ach_count,
            hours=hltb.hours,
        )
        async with write_lock:
            excel.append_game(entry)
            progress.mark_processed(game.appid)

    tasks = [process_one(g, i) for i, g in enumerate(pending, 1)]
    await asyncio.gather(*tasks)

    print("\nOrdenando e numerando...")
    excel.sort_and_number()
    print("Concluído.")


async def run_retry(
    steam_id: str,
    progress: Progress,
    excel: ExcelWriter,
    client: SteamClient,
) -> None:
    no_hltb = list(progress.no_hltb)
    if no_hltb:
        total = len(no_hltb)
        print(f"\n{total} jogos sem HLTB para retentar.\n")

        hltb_sem   = asyncio.Semaphore(HLTB_SEM)
        steam_sem  = asyncio.Semaphore(STEAM_SEM)
        write_lock = asyncio.Lock()
        found: list[NoHLTBGame] = []

        async def retry_one(entry: NoHLTBGame, idx: int) -> None:
            async def fetch_hltb_retry():
                async with hltb_sem:
                    return await hltb_search(entry.name)

            async def fetch_status_retry():
                async with steam_sem:
                    return await client.get_player_status(
                        steam_id, entry.appid, 1, entry.achievements
                    )

            hltb, status = await asyncio.gather(fetch_hltb_retry(), fetch_status_retry())

            if hltb is None:
                print(f"[{idx}/{total}] {entry.name} — {entry.achievements} conquistas — ainda sem HLTB")
                return

            print(f"[{idx}/{total}] {entry.name} — {entry.achievements} conquistas — {hltb.hours}h (HLTB) — {status} ✓")
            game_entry = Game(
                name=entry.name,
                status=status,
                link_hltb=hltb.url,
                achievements=entry.achievements,
                hours=hltb.hours,
            )
            async with write_lock:
                excel.append_game(game_entry)
                found.append(entry)

        tasks = [retry_one(e, i) for i, e in enumerate(no_hltb, 1)]
        await asyncio.gather(*tasks)

        if found:
            for e in found:
                progress.no_hltb.remove(e)
            progress.save()
            print(f"\n{len(found)} jogos adicionados. Reordenando...")
            excel.sort_and_number()
    else:
        print("Nenhum jogo sem HLTB para retentar.")

    print("\nAtualizando status dos jogos não-platinados...")
    name_to_game = {g.name: g for g in await client.get_owned_games(steam_id)}
    changed = excel.update_statuses(name_to_game, client, steam_id)
    if changed:
        print(f"\n{changed} status atualizado(s).")
    else:
        print("Nenhuma mudança de status.")


def _press_enter() -> None:
    input("\nPressione Enter para continuar...")


async def _main_loop() -> None:
    api_key = os.getenv("STEAM_API_KEY", "").strip()
    if not api_key:
        print("Erro: STEAM_API_KEY não definida no .env")
        sys.exit(1)

    async with aiohttp.ClientSession() as session:
        client = SteamClient(session, api_key)
        progress = Progress.load()

        # Fluxo de primeiro uso
        if not progress.steam_id:
            env_profile = os.getenv("STEAM_PROFILE", "").strip()
            raw = env_profile or input("Digite o perfil Steam (URL ou SteamID64): ").strip()
            token = _resolve_steam_input(raw)
            if not token:
                print("Entrada inválida.")
                sys.exit(1)
            steam_id = await _ensure_steam_id(token, client)
            progress.steam_id = steam_id
            progress.save()
        else:
            steam_id = progress.steam_id
            print(f"Retomando sessão para SteamID {steam_id}")

        while True:
            print("\n========== SteamPlatViewer ==========")
            print(" [1] Continuar processamento")
            print(" [2] Retentar sem-HLTB + atualizar status")
            print(" [3] Reiniciar do zero")
            print(" [0] Sair")
            print("=====================================")
            choice = input("Opção: ").strip()

            if choice == "0":
                print("Saindo.")
                break

            elif choice == "1":
                excel = ExcelWriter.load() or ExcelWriter.new()
                await run_processing(steam_id, progress, excel, client)
                _press_enter()

            elif choice == "2":
                excel = ExcelWriter.load()
                if excel is None:
                    print("Nenhum arquivo Excel encontrado. Execute a opção 1 primeiro.")
                else:
                    await run_retry(steam_id, progress, excel, client)
                _press_enter()

            elif choice == "3":
                confirm = input("Isso apagará todo o progresso. Confirma? (s/N): ").strip().lower()
                if confirm == "s":
                    progress.clear()
                    env_profile = os.getenv("STEAM_PROFILE", "").strip()
                    raw = env_profile or input("Digite o perfil Steam (URL ou SteamID64): ").strip()
                    token = _resolve_steam_input(raw)
                    if not token:
                        print("Entrada inválida.")
                        continue
                    steam_id = await _ensure_steam_id(token, client)
                    progress.steam_id = steam_id
                    progress.save()
                    excel = ExcelWriter.new()
                    await run_processing(steam_id, progress, excel, client)
                    _press_enter()
            else:
                print("Opção inválida.")


def main() -> None:
    asyncio.run(_main_loop())


if __name__ == "__main__":
    main()
