"""
Steam Workshop Monitor для DayZ (appid=221100)

Парсит популярные моды со Steam Workshop, отслеживает новые,
отправляет через AI для описания на русском и публикует в Telegram.

Источники данных:
  1) Steam Workshop Web API (IPublishedFileService/QueryFiles) — если есть API ключ
  2) Scraping Steam Community Workshop страницы + бесплатный GetPublishedFileDetails API (fallback)

Хранение состояния:
  workshop_state.json — {"posted_ids": [...], "last_check": "ISO", "known_ids": [...]}
"""

import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Optional

import aiohttp

logger = logging.getLogger("steam_workshop_monitor")

# ─── Конфиг ────────────────────────────────────────────────────────────────────
DAYZ_APPID = 221100
STEAM_WORKSHOP_URL = (
    "https://steamcommunity.com/workshop/browse/"
    "?appid=221100"
    "&browsesort=mostpopular"
    "&browsefilter=trend"
    "&section=readytouseitems"
    "&p=1&numperpage=30"
)

STEAM_API_URL = "https://api.steampowered.com/IPublishedFileService/QueryFiles/v1/"

# ─── State persistence ────────────────────────────────────────────────────────

STATE_FILE = os.path.join(os.path.dirname(__file__), "workshop_state.json")


def _load_state() -> dict:
    """Загрузить состояние из JSON файла."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning("Не удалось загрузить workshop_state.json: %s", e)
    return {"posted_ids": [], "last_check": None, "known_ids": []}


def _save_state(state: dict) -> None:
    """Сохранить состояние в JSON файл."""
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except IOError as e:
        logger.error("Не удалось сохранить workshop_state.json: %s", e)


# ─── Steam Workshop scraping ───────────────────────────────────────────────────

async def _fetch_mod_details_via_web(mod_ids: list) -> list:
    """
    Получает детали для каждого мода через Steam API GetPublishedFileDetails.
    Работает БЕЗ API ключа (бесплатный endpoint).
    """
    mods = []
    if not mod_ids:
        return mods

    url = "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/"
    batch_size = 50

    for i in range(0, len(mod_ids), batch_size):
        batch = mod_ids[i : i + batch_size]

        data = {"itemcount": len(batch)}
        for idx, mod_id in enumerate(batch):
            data[f"publishedfileids[{idx}]"] = mod_id
            data[f"children[{idx}]"] = ""

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, data=data, timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    if resp.status != 200:
                        logger.warning("Steam API вернул статус %d", resp.status)
                        continue

                    result = await resp.json()
                    items = result.get("response", {}).get(
                        "publishedfiledetails", []
                    )

                    for item in items:
                        mod = _parse_api_item(item)
                        if mod:
                            mods.append(mod)

        except Exception as e:
            logger.error("Ошибка при получении деталей модов: %s", e)

    return mods


def _parse_api_item(item: dict) -> Optional[dict]:
    """Парсит один элемент из Steam API ответа в формат мода."""
    try:
        mod_id = item.get("publishedfileid", "")
        if not mod_id:
            return None

        file_size = item.get("file_size", 0)
        if file_size > 1024 * 1024:
            size_str = f"{file_size / (1024 * 1024):.1f} MB"
        elif file_size > 1024:
            size_str = f"{file_size / 1024:.1f} KB"
        else:
            size_str = f"{file_size} B"

        time_updated = item.get("time_updated", 0)
        updated_str = ""
        if time_updated:
            updated_str = datetime.fromtimestamp(
                time_updated, tz=timezone.utc
            ).strftime("%d.%m.%Y")

        tags = item.get("tags", [])
        if isinstance(tags, list):
            tags = [t.get("tag", "") for t in tags if isinstance(t, dict)]
        elif isinstance(tags, str):
            tags = tags.split(",")

        return {
            "id": mod_id,
            "title": item.get("title", "Без названия").strip(),
            "description": item.get("description", "").strip(),
            "author": item.get("creator", "").strip(),
            "image_url": item.get("preview_url", ""),
            "size": size_str,
            "file_size": file_size,
            "updated": updated_str,
            "timestamp": time_updated,
            "url": f"https://steamcommunity.com/sharedfiles/filedetails/?id={mod_id}",
            "subscriptions": item.get("subscriptions", 0),
            "favorited": item.get("favorited", 0),
            "lifetime_subscriptions": item.get("lifetime_subscriptions", 0),
            "lifetime_favorited": item.get("lifetime_favorited", 0),
            "views": item.get("views", 0),
            "tags": tags,
        }

    except Exception as e:
        logger.error("Ошибка парсинга элемента мода: %s", e)
        return None


async def _fetch_workshop_page_html(session: aiohttp.ClientSession) -> Optional[str]:
    """Получает HTML страницы Steam Workshop для DayZ."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    try:
        async with session.get(
            STEAM_WORKSHOP_URL,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            if resp.status == 200:
                return await resp.text()
            else:
                logger.warning(
                    "Steam Workshop вернул статус %d", resp.status
                )
    except Exception as e:
        logger.error("Ошибка загрузки страницы Steam Workshop: %s", e)

    return None


# ─── Основная логика монитора ──────────────────────────────────────────────────

async def fetch_popular_mods(
    steam_api_key: Optional[str] = None,
    max_mods: int = 10,
) -> list:
    """
    Получает список популярных модов DayZ со Steam Workshop.

    Приоритет:
      1) Если есть steam_api_key — использует IPublishedFileService/QueryFiles
      2) Иначе — scrapes страницу Workshop + GetPublishedFileDetails (бесплатный API)
    """
    mods = []

    if steam_api_key:
        mods = await _fetch_via_steam_api(steam_api_key, max_mods)

    if not mods:
        mods = await _fetch_via_scraping(max_mods)

    return mods


async def _fetch_via_steam_api(api_key: str, max_mods: int) -> list:
    """Получает популярные моды через Steam Web API (нужен API ключ)."""
    mods = []

    params = {
        "key": api_key,
        "query_type": 1,  # k_EQueryType_RankedByTotalUniqueSubscriptions
        "cursor": "*",
        "numperpage": max_mods,
        "appid": DAYZ_APPID,
        "return_short_description": "true",
        "return_children": "false",
        "return_tags": "true",
        "return_previews": "true",
        "return_details": "true",
        "return_for_sale_data": "false",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                STEAM_API_URL,
                params=params,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    logger.warning("Steam Web API вернул статус %d", resp.status)
                    return []

                result = await resp.json()
                items = result.get("response", {}).get(
                    "publishedfiledetails", []
                )

                for item in items:
                    mod = _parse_api_item(item)
                    if mod:
                        mods.append(mod)

    except Exception as e:
        logger.error("Ошибка Steam Web API: %s", e)

    return mods


async def _fetch_via_scraping(max_mods: int) -> list:
    """
    Fallback: скрапит страницу Workshop, извлекает ID модов,
    затем получает детали через бесплатный API.
    """
    async with aiohttp.ClientSession() as session:
        html = await _fetch_workshop_page_html(session)
        if not html:
            logger.error("Не удалось получить страницу Steam Workshop")
            return []

        id_pattern = re.compile(r"filedetails/\?id=(\d+)")
        all_ids = list(set(id_pattern.findall(html)))
        logger.info("Найдено %d ID модов на странице Workshop", len(all_ids))

        if not all_ids:
            return []

        mod_ids = all_ids[:max_mods]
        mods = await _fetch_mod_details_via_web(mod_ids)

    return mods


async def check_for_new_mods(
    steam_api_key: Optional[str] = None,
    min_subscriptions: int = 100,
    days_old: int = 7,
) -> list:
    """
    Проверяет наличие новых популярных модов за последние N дней.
    Фильтрует по подписчикам и отслеживает уже опубликованные.
    """
    state = _load_state()
    known_ids = set(state.get("known_ids", []))
    posted_ids = set(state.get("posted_ids", []))

    mods = await fetch_popular_mods(steam_api_key=steam_api_key, max_mods=50)

    now = time.time()
    cutoff = now - (days_old * 24 * 3600)

    new_mods = []
    for mod in mods:
        mod_id = mod["id"]

        if mod_id not in known_ids:
            known_ids.add(mod_id)

        if mod_id in posted_ids:
            continue

        if mod.get("timestamp", 0) < cutoff:
            continue

        if mod.get("subscriptions", 0) < min_subscriptions:
            continue

        new_mods.append(mod)

    state["known_ids"] = list(known_ids)
    state["last_check"] = datetime.now(timezone.utc).isoformat()
    _save_state(state)

    if new_mods:
        logger.info("Найдено %d новых популярных модов", len(new_mods))
    else:
        logger.info("Новых популярных модов не найдено")

    return new_mods


# ─── Telegram formatting ───────────────────────────────────────────────────────

def format_mod_message(mod: dict, ai_summary: Optional[str] = None) -> dict:
    """Форматирует данные мода для отправки в Telegram."""
    icon = "🔧"

    tags = mod.get("tags", [])
    if isinstance(tags, list):
        tag_str = ", ".join(tags[:5])
    else:
        tag_str = str(tags)

    subs = mod.get("subscriptions", 0)
    favs = mod.get("favorited", 0)
    views = mod.get("views", 0)

    parts = [
        f"{icon} <b>{_escape_html(mod['title'])}</b>",
        "",
    ]

    author = mod.get("author", "").strip()
    if author:
        parts.append(f"👤 Автор: {_escape_html(author)}")

    if ai_summary:
        parts.append("")
        parts.append(ai_summary)
    else:
        desc = mod.get("description", "").strip()
        if desc:
            clean_desc = re.sub(r"<[^>]+>", "", desc)
            clean_desc = clean_desc.strip()[:300]
            if clean_desc:
                parts.append("")
                parts.append(_escape_html(clean_desc))

    parts.append("")

    if tag_str:
        parts.append(f"🏷 Теги: {tag_str}")

    stats_parts = []
    if subs:
        stats_parts.append(f"📥 {subs:,}")
    if favs:
        stats_parts.append(f"⭐ {favs:,}")
    if views:
        stats_parts.append(f"👁 {views:,}")

    if stats_parts:
        parts.append(f"📊 {', '.join(stats_parts)}")

    size = mod.get("size", "")
    if size:
        parts.append(f"💾 Размер: {size}")

    updated = mod.get("updated", "")
    if updated:
        parts.append(f"📅 Обновлён: {updated}")

    parts.append("")
    parts.append(f'🔗 <a href="{mod["url"]}">Открыть в Steam Workshop</a>')

    text = "\n".join(parts)

    return {
        "text": text,
        "photo_url": mod.get("image_url", ""),
        "mod_id": mod["id"],
    }


def _escape_html(text: str) -> str:
    """Экранирует HTML спецсимволы для Telegram."""
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    return text


# ─── Основной цикл ─────────────────────────────────────────────────────────────

async def run_workshop_monitor(
    telegram_bot=None,
    db=None,
    ai_analyzer=None,
    web_panel_url: str = "",
    web_panel_api_key: str = "",
    steam_api_key: Optional[str] = None,
    check_interval: int = 3600,
    min_subscriptions: int = 100,
    ai_analyze: bool = True,
):
    """Основной цикл монитора Steam Workshop.

    Контент идёт через модерацию:
      1. Сохраняется в БД как сообщение (source_type='workshop')
      2. Отправляется на веб-панель для модерации
      3. Публикуется в Telegram ТОЛЬКО после одобрения на панели
    """
    logger.info(
        "Steam Workshop Monitor запущен (интервал: %d сек, мин. подписчиков: %d)",
        check_interval,
        min_subscriptions,
    )

    while True:
        try:
            logger.info("Проверяем Steam Workshop на новые моды...")
            new_mods = await check_for_new_mods(
                steam_api_key=steam_api_key,
                min_subscriptions=min_subscriptions,
                days_old=7,
            )

            for mod in new_mods:
                try:
                    logger.info(
                        "Обрабатываем мод: %s (ID: %s)", mod["title"], mod["id"]
                    )

                    ai_summary = None
                    ai_analysis_result = None
                    if ai_analyze and ai_analyzer:
                        try:
                            ai_analysis_result = await ai_analyzer.analyze_workshop_mod(mod)
                            if ai_analysis_result:
                                ai_summary = ai_analysis_result.get("summary", "")
                        except Exception as e:
                            logger.error("AI анализ мода %s не удался: %s", mod["id"], e)
                    elif ai_analyze:
                        # Fallback: standalone-анализ без экземпляра анализатора
                        try:
                            from ai_analyzer import analyze_workshop_mod
                            ai_analysis_result = await analyze_workshop_mod(mod)
                            if ai_analysis_result:
                                ai_summary = ai_analysis_result.get("summary", "")
                        except Exception as e:
                            logger.error("AI анализ мода %s не удался: %s", mod["id"], e)

                    msg = format_mod_message(mod, ai_summary)

                    # --- Модерация: сохраняем в БД + отправляем на веб-панель ---
                    saved_to_db = False
                    if db:
                        try:
                            images = [mod.get("image_url")] if mod.get("image_url") else []
                            links = [mod.get("url")] if mod.get("url") else []
                            msg_id = await db.save_message(
                                external_id=mod["id"],
                                source_type="workshop",
                                source_id="steam_workshop",
                                server_name="Steam Workshop",
                                text=mod.get("description", "") or mod.get("title", ""),
                                title=mod.get("title", ""),
                                author=mod.get("author", ""),
                                images=images,
                                links=links,
                            )
                            if msg_id:
                                # Сохраняем результат AI-анализа
                                news_type = ai_analysis_result.get("news_type", "mod_update") if ai_analysis_result else "mod_update"
                                priority = ai_analysis_result.get("priority", "medium") if ai_analysis_result else "medium"
                                summary = ai_analysis_result.get("summary", "") if ai_analysis_result else ""
                                formatted_post = ai_analysis_result.get("formatted_post", msg.get("text", "")) if ai_analysis_result else msg.get("text", "")

                                await db.save_processed(
                                    message_id=msg_id,
                                    news_type=news_type,
                                    priority=priority,
                                    should_publish=False,
                                    summary=summary,
                                    server_name="Steam Workshop",
                                    formatted_post=formatted_post,
                                )
                                saved_to_db = True
                                logger.info(
                                    "Мод '%s' #%d отправлен на модерацию (type=%s, priority=%s)",
                                    mod["title"], msg_id, news_type, priority,
                                )
                        except Exception as e:
                            logger.error("Ошибка сохранения мода %s в БД: %s", mod["id"], e)

                    # Отправляем на веб-панель для модерации
                    if web_panel_url:
                        try:
                            from web_app_integration import send_to_web_panel
                            success = await send_to_web_panel(
                                news_data={
                                    "externalId": mod["id"],
                                    "serverName": "Steam Workshop",
                                    "content": mod.get("description", "") or mod.get("title", ""),
                                    "summary": ai_summary or "",
                                    "formattedPost": msg.get("text", ""),
                                    "newsType": ai_analysis_result.get("news_type", "mod_update") if ai_analysis_result else "mod_update",
                                    "priority": ai_analysis_result.get("priority", "medium") if ai_analysis_result else "medium",
                                    "images": [mod.get("image_url")] if mod.get("image_url") else [],
                                },
                                web_app_url=web_panel_url,
                                bot_api_key=web_panel_api_key or None,
                            )
                            if success:
                                logger.info("Мод '%s' отправлен на веб-панель", mod["title"])
                            else:
                                logger.error("Веб-панель: не удалось отправить мод '%s'", mod["title"])
                        except ImportError:
                            logger.warning("web_app_integration не найден — модерация через панель недоступна")
                        except Exception as e:
                            logger.error("Ошибка отправки мода на веб-панель: %s", e)
                    elif not saved_to_db:
                        # Нет БД и нет веб-панели — fallback: прямой отправ (старое поведение)
                        if telegram_bot:
                            await telegram_bot.send_workshop_post(msg)
                            logger.info("Мод '%s' опубликован в Telegram (без модерации — нет БД/панели)", mod["title"])

                    # Отмечаем как отправленный в state
                    state = _load_state()
                    if mod["id"] not in state.get("posted_ids", []):
                        state["posted_ids"].append(mod["id"])
                        _save_state(state)

                except Exception as e:
                    logger.error("Ошибка обработки мода %s: %s", mod.get("id", "unknown"), e)

        except Exception as e:
            logger.error("Ошибка в основном цикле Workshop монитора: %s", e)

        logger.info("Следующая проверка через %d секунд...", check_interval)
        await asyncio.sleep(check_interval)


# ─── Тестовый запуск ───────────────────────────────────────────────────────────

async def test_fetch():
    """Тестовая функция для проверки работы монитора."""
    print("=" * 60)
    print("🔍 Тест Steam Workshop Monitor")
    print("=" * 60)

    print("\n📡 Получаем популярные моды DayZ...")
    mods = await fetch_popular_mods(max_mods=5)

    if not mods:
        print("❌ Не удалось получить моды. Проверьте интернет-соединение.")
        return

    print(f"✅ Получено {len(mods)} модов\n")

    for i, mod in enumerate(mods, 1):
        print(f"{'─' * 50}")
        print(f"  #{i}: {mod.get('title', 'Без названия')}")
        print(f"  ID: {mod.get('id', '?')}")
        print(f"  Автор: {mod.get('author', '?')}")
        print(f"  Подписчики: {mod.get('subscriptions', 0):,}")
        print(f"  Обновлён: {mod.get('updated', '?')}")
        print(f"  Размер: {mod.get('size', '?')}")

    print("\n✅ Тест завершён успешно!")


if __name__ == "__main__":
    asyncio.run(test_fetch())
