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
import os
import re
import time
from datetime import datetime, timezone
from typing import Optional

import aiohttp

from logger import logger
from monitor_stats import stats

# ─── Конфиг ────────────────────────────────────────────────────────────────────
DAYZ_APPID = 221100

def _make_workshop_url(sort: str = "mostpopular", filter: str = "trend", page: int = 1, numperpage: int = 30) -> str:
    return (
        "https://steamcommunity.com/workshop/browse/"
        f"?appid={DAYZ_APPID}"
        f"&browsesort={sort}"
        f"&browsefilter={filter}"
        "&section=readytouseitems"
        f"&p={page}&numperpage={numperpage}"
    )

# Страницы для скрапинга — trending (популярные) + updated (недавно обновлённые)
WORKSHOP_SCRAPE_URLS = [
    _make_workshop_url(sort="mostpopular", filter="trend"),
    _make_workshop_url(sort="mostrecent", filter="all"),
    _make_workshop_url(sort="lastupdated", filter="all"),
]

STEAM_API_URL = "https://api.steampowered.com/IPublishedFileService/QueryFiles/v1/"

# ─── State persistence ────────────────────────────────────────────────────────

STATE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "workshop_state.json")


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


def _safe_int(val, default=0) -> int:
    """Конвертирует значение в int. Steam API часто возвращает числа как строки."""
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


async def _resolve_author_names(mods: list) -> None:
    """Парсит имена авторов со страниц Workshop для каждого мода (in-place).
    Бесплатно, без API ключа — берёт имя из HTML страницы мода."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    # Собираем уникальные creator ID для которых ещё нет имени
    to_resolve = {}
    for mod in mods:
        author = mod.get("author", "").strip()
        if author and author.isdigit() and not mod.get("author_name"):
            to_resolve[author] = mod.get("id", "")

    if not to_resolve:
        return

    logger.info("Резолвим имена для %d авторов...", len(to_resolve))

    try:
        async with aiohttp.ClientSession() as session:
            for steam_id, mod_id in to_resolve.items():
                try:
                    url = f"https://steamcommunity.com/workshop/filedetails/?id={mod_id}"
                    async with session.get(
                        url, headers=headers,
                        timeout=aiohttp.ClientTimeout(total=15),
                    ) as resp:
                        if resp.status != 200:
                            continue
                        html = await resp.text()

                    # Ищем имя автора в блоке: <div class="workshopItemAuthorName">
                    match = re.search(
                        r'class="workshopItemAuthorName"[^>]*>\s*<a[^>]*>([^<]+)<',
                        html,
                    )
                    if match:
                        name = match.group(1).strip()
                        # Обновляем все моды этого автора
                        for mod in mods:
                            if mod.get("author") == steam_id:
                                mod["author_name"] = name
                        logger.debug("Автор %s → %s", steam_id, name)

                    await asyncio.sleep(0.3)  # Не спамим Steam

                except Exception as e:
                    logger.debug("Не удалось резолвить автора %s: %s", steam_id, e)
    except Exception as e:
        logger.warning("Ошибка при резолвинге авторов: %s", e)


def _parse_api_item(item: dict) -> Optional[dict]:
    """Парсит один элемент из Steam API ответа в формат мода."""
    try:
        mod_id = str(item.get("publishedfileid", "")).strip()
        if not mod_id:
            return None

        file_size = _safe_int(item.get("file_size", 0))
        if file_size > 1024 * 1024:
            size_str = f"{file_size / (1024 * 1024):.1f} MB"
        elif file_size > 1024:
            size_str = f"{file_size / 1024:.1f} KB"
        else:
            size_str = f"{file_size} B"

        time_updated = _safe_int(item.get("time_updated", 0))
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
            "title": str(item.get("title", "Без названия")).strip(),
            "description": str(item.get("description", "")).strip(),
            "author": str(item.get("creator", "")).strip(),
            "image_url": str(item.get("preview_url", "")).strip(),
            "size": size_str,
            "file_size": file_size,
            "updated": updated_str,
            "timestamp": time_updated,
            "url": f"https://steamcommunity.com/sharedfiles/filedetails/?id={mod_id}",
            "subscriptions": _safe_int(item.get("subscriptions", 0)),
            "favorited": _safe_int(item.get("favorited", 0)),
            "lifetime_subscriptions": _safe_int(item.get("lifetime_subscriptions", 0)),
            "lifetime_favorited": _safe_int(item.get("lifetime_favorited", 0)),
            "views": _safe_int(item.get("views", 0)),
            "tags": tags,
        }

    except Exception as e:
        logger.error("Ошибка парсинга элемента мода: %s", e)
        return None


async def _fetch_workshop_page_html(session: aiohttp.ClientSession, url: str | None = None) -> Optional[str]:
    """Получает HTML страницы Steam Workshop для DayZ."""
    if url is None:
        url = WORKSHOP_SCRAPE_URLS[0]
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    try:
        async with session.get(
            url,
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
    has_key = bool(steam_api_key)
    logger.info("[WS] Запрос популярных модов (метод: %s, лимит: %d)",
                "Steam Web API" if has_key else "scraping", max_mods)
    stats.set_status("workshop", "checking", f"запрос модов ({'API' if has_key else 'scraping'})")

    mods = []

    if has_key:
        logger.info("[WS] Пробуем Steam Web API (IPublishedFileService/QueryFiles)...")
        mods = await _fetch_via_steam_api(steam_api_key, max_mods)
        if mods:
            logger.info("[WS] Steam Web API: получено %d модов", len(mods))
        else:
            logger.warning("[WS] Steam Web API вернул пустой результат — падаем на scraping")

    if not mods:
        mods = await _fetch_via_scraping(max_mods)

    logger.info("[WS] Итого получено %d модов из Steam Workshop", len(mods))
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
    Fallback: скрапит несколько страниц Workshop (trending, recent, updated),
    извлекает ID модов, затем получает детали через бесплатный API.
    """
    id_pattern = re.compile(r"filedetails/\?id=(\d+)")
    all_ids = set()
    pages_ok = 0
    pages_fail = 0

    logger.info("[WS-SCAN] Скрапинг Workshop: %d страниц (метод: scraping + GetPublishedFileDetails)",
                len(WORKSHOP_SCRAPE_URLS))
    stats.set_status("workshop", "checking", "скрапинг страниц Workshop")

    async with aiohttp.ClientSession() as session:
        for i, url in enumerate(WORKSHOP_SCRAPE_URLS, 1):
            sort_info = url.split("&")[3] if "&" in url else "?"
            logger.info("[WS-SCAN] Страница %d/%d: %s", i, len(WORKSHOP_SCRAPE_URLS), sort_info)
            html = await _fetch_workshop_page_html(session, url)
            if html:
                found = set(id_pattern.findall(html))
                all_ids |= found
                pages_ok += 1
                logger.info("[WS-SCAN] Страница %d: OK — найдено %d ID модов", i, len(found))
            else:
                pages_fail += 1
                logger.warning("[WS-SCAN] Страница %d: не удалось загрузить", i)
            await asyncio.sleep(0.5)

    logger.info("[WS-SCAN] Итого: %d уникальных ID модов (страниц OK: %d, FAIL: %d)",
                len(all_ids), pages_ok, pages_fail)
    stats.increment("workshop", "errors", pages_fail)

    if not all_ids:
        logger.warning("[WS-SCAN] Ни одного ID мода не найдено — проверьте доступность Steam")
        return []

    mod_ids = list(all_ids)[:max_mods]
    logger.info("[WS-SCAN] Запрос деталей для %d модов через GetPublishedFileDetails API...", len(mod_ids))
    mods = await _fetch_mod_details_via_web(mod_ids)
    logger.info("[WS-SCAN] Получено деталей: %d из %d запросов", len(mods), len(mod_ids))

    return mods


async def check_for_new_mods(
    steam_api_key: Optional[str] = None,
    min_subscriptions: int = 100,
    days_old: int = 30,
    max_per_check: int = 3,
) -> list:
    """
    Проверяет наличие новых популярных модов.

    На первом запуске (пустой state):
      - Помечает ВСЕ старые моды как известные (не спамит)
      - Берёт только TOP-N самых популярных за последние 3 дней

    При обычных проверках:
      - Возвращает до max_per_check новых модов за последние days_old дней
      - Сортировка по подписчикам (больше = лучше)
      - days_old=30 чтобы моды, набравшие популярность через несколько недель,
        тоже попадали в выборку
    """
    state = _load_state()
    known_ids = set(state.get("known_ids", []))
    posted_ids = set(state.get("posted_ids", []))
    is_first_run = not state.get("last_check")

    logger.info("[WS-FILTER] Начало фильтрации (known: %d, posted: %d, первый запуск: %s, мин. подписчиков: %d, дней: %d)",
                len(known_ids), len(posted_ids), is_first_run, min_subscriptions, days_old)

    mods = await fetch_popular_mods(steam_api_key=steam_api_key, max_mods=80)
    stats.increment("workshop", "found", len(mods))

    now = time.time()

    if is_first_run:
        # === ПЕРВЫЙ ЗАПУСК: не спамим старьём ===
        logger.info("[WS-FILTER] ПЕРВЫЙ ЗАПУСК: фильтруем старые моды (cutoff: 3 дня)")
        cutoff_3d = now - (3 * 24 * 3600)

        fresh = []
        skipped_old = 0
        skipped_posted = 0
        for mod in mods:
            mod_id = mod["id"]
            if mod_id not in known_ids:
                known_ids.add(mod_id)
            if mod_id in posted_ids:
                skipped_posted += 1
                continue
            if mod.get("timestamp", 0) and mod["timestamp"] < cutoff_3d:
                known_ids.add(mod_id)
                skipped_old += 1
                continue
            fresh.append(mod)

        state["known_ids"] = list(known_ids)
        state["last_check"] = datetime.now(timezone.utc).isoformat()
        _save_state(state)

        before_subs = len(fresh)
        fresh = [m for m in fresh if m.get("subscriptions", 0) >= min_subscriptions]
        filtered_by_subs = before_subs - len(fresh)
        fresh.sort(key=lambda x: x.get("subscriptions", 0), reverse=True)
        result = fresh[:max_per_check]

        logger.info(
            "[WS-FILTER] Первый запуск: всего=%d, старых=%d, уже отправленных=%d, после фильтра подписок=%d, итог=%d",
            len(mods), skipped_old, skipped_posted, len(fresh), len(result),
        )
        stats.increment("workshop", "skipped", skipped_old + skipped_posted + filtered_by_subs)
        return result

    # === ОБЫЧНАЯ ПРОВЕРКА ===
    cutoff = now - (days_old * 24 * 3600)

    new_mods = []
    skipped_known = 0
    skipped_posted = 0
    skipped_date = 0
    skipped_subs = 0

    for mod in mods:
        mod_id = mod["id"]
        if mod_id not in known_ids:
            known_ids.add(mod_id)
        else:
            skipped_known += 1

        if mod_id in posted_ids:
            skipped_posted += 1
            continue
        if mod.get("timestamp", 0) < cutoff:
            skipped_date += 1
            continue
        if mod.get("subscriptions", 0) < min_subscriptions:
            skipped_subs += 1
            continue
        new_mods.append(mod)

    # Очистка known_ids от старых записей
    if len(known_ids) > 500:
        keep = set(list(known_ids)[-300:])
        known_ids = keep | posted_ids
        logger.info("[WS-FILTER] Очистка known_ids: %d → %d записей", len(state.get("known_ids", [])), len(known_ids))

    state["known_ids"] = list(known_ids)
    state["last_check"] = datetime.now(timezone.utc).isoformat()
    _save_state(state)

    # Сортировка по популярности
    new_mods.sort(key=lambda x: x.get("subscriptions", 0), reverse=True)
    result = new_mods[:max_per_check]

    total_skipped = skipped_known + skipped_posted + skipped_date + skipped_subs
    logger.info(
        "[WS-FILTER] Фильтрация: всего=%d → известных=%d, отправленных=%d, старых=%d, малоподписных=%d → новых=%d → итог=%d",
        len(mods), skipped_known, skipped_posted, skipped_date, skipped_subs,
        len(new_mods), len(result),
    )
    stats.increment("workshop", "skipped", total_skipped)

    if result:
        for m in result[:5]:
            logger.info("[WS-FILTER]   → '%s' (подписчиков: %d)", m.get('title', '?')[:50], m.get('subscriptions', 0))

    return result


# ─── Telegram formatting ───────────────────────────────────────────────────────

# ─── Категории модов по тегам ──────────────────────────────────────────────

_TAG_CATEGORY_MAP = {
    "vehicle": "🚗 Транспорт",
    "car": "🚗 Транспорт",
    "boat": "🚗 Транспорт",
    "helicopter": "🚗 Транспорт",
    "aircraft": "🚗 Транспорт",
    "plane": "🚗 Транспорт",
    "truck": "🚗 Транспорт",
    "bicycle": "🚗 Транспорт",
    "transport": "🚗 Транспорт",
    "weapon": "🔫 Оружие",
    "gun": "🔫 Оружие",
    "rifle": "🔫 Оружие",
    "pistol": "🔫 Оружие",
    "melee": "🔫 Оружие",
    "ammo": "🔫 Оружие",
    "ammunition": "🔫 Оружие",
    "building": "🏗 Строительство",
    "base": "🏗 Строительство",
    "basebuilding": "🏗 Строительство",
    "cabin": "🏗 Строительство",
    "shelter": "🏗 Строительство",
    "tent": "🏗 Строительство",
    "map": "🗺 Карты",
    "terrain": "🗺 Карты",
    "chernarus": "🗺 Карты",
    "livonia": "🗺 Карты",
    "clothing": "👔 Одежда",
    "clothes": "👔 Одежда",
    "armor": "👔 Одежда",
    "uniform": "👔 Одежда",
    "backpack": "👔 Одежда",
    "food": "🍔 Еда",
    "drink": "🍔 Еда",
    "medical": "💊 Медицина",
    "health": "💊 Медицина",
    "zombie": "🧟 Зомби",
    "infected": "🧟 Зомби",
    "animal": "🐾 Животные",
    "ai": "🤖 AI / NPC",
    "npc": "🤖 AI / NPC",
    "trader": "🤖 AI / NPC",
    "pvp": "⚔ PVP",
    "pve": "🕊 PVE",
    "roleplay": "🎭 Ролевая игра",
    "rp": "🎭 Ролевая игра",
    "ui": "🖥 Интерфейс",
    "hud": "🖥 Интерфейс",
    "menu": "🖥 Интерфейс",
    "crafting": "🔧 Крафт",
    "craft": "🔧 Крафт",
    "emotes": "🎬 Анимации",
    "animation": "🎬 Анимации",
    "effects": "✨ Эффекты",
    "weather": "🌤 Погода",
    "graphics": "🎨 Графика",
    "sound": "🔊 Звук",
    "audio": "🔊 Звук",
    "server": "🖥 Сервер",
    "admin": "🖥 Сервер",
    "tool": "🔧 Утилиты",
    "utility": "🔧 Утилиты",
    "mod": "🔧 Утилиты",
    "dayz": "🎮 DayZ",
}

_DEFAULT_CATEGORY = "📦 Мод"


def _detect_category(tags: list) -> str:
    """Определяет категорию мода по тегам."""
    if not tags:
        return _DEFAULT_CATEGORY
    lowered = [t.lower().strip() for t in tags]
    for tag, category in _TAG_CATEGORY_MAP.items():
        if tag in lowered:
            return category
    return _DEFAULT_CATEGORY


def _format_author_display(mod: dict) -> str:
    """Форматирует имя автора. Если есть resolved_name — использует его, иначе обрезает длинный SteamID."""
    resolved = mod.get("author_name", "").strip()
    steam_id = mod.get("author", "").strip()

    if resolved:
        return _escape_html(resolved)

    if steam_id and not steam_id.isdigit():
        # Already a name, not a numeric ID
        return _escape_html(steam_id)

    if steam_id:
        # Numeric SteamID — не показываем
        return ""

    return "Неизвестен"


def format_mod_message(mod: dict, ai_summary: Optional[str] = None) -> dict:
    """Форматирует данные мода для отправки в Telegram."""
    tags = mod.get("tags", [])
    if isinstance(tags, list):
        tag_str = ", ".join(tags[:5])
    else:
        tag_str = str(tags)

    category = _detect_category(tags)
    author = _format_author_display(mod)
    subs = mod.get("subscriptions", 0)
    favs = mod.get("favorited", 0)
    views = mod.get("views", 0)

    # ── Заголовок ──
    parts = [
        f"<b>{_escape_html(mod['title'])}</b>",
    ]

    # ── Автор ──
    if author:
        parts.append(f"└ от {author}")

    # ── Разделитель ──
    parts.append("")

    # ── Описание ──
    if ai_summary:
        parts.append(ai_summary)
    else:
        desc = mod.get("description", "").strip()
        if desc:
            clean_desc = re.sub(r"<[^>]+>", "", desc)
            clean_desc = clean_desc.strip()[:300]
            if clean_desc:
                parts.append(_escape_html(clean_desc))

    # ── Разделитель ──
    parts.append("")

    # ── Статистика ──
    stats_parts = []
    if subs:
        stats_parts.append(f"📥 {subs:,}")
    if favs:
        stats_parts.append(f"⭐ {favs:,}")
    if views:
        stats_parts.append(f"👁 {views:,}")
    if stats_parts:
        parts.append(f"📊 {' │ '.join(stats_parts)}")

    # ── Мета ──
    meta_parts = []
    size = mod.get("size", "")
    if size:
        meta_parts.append(f"💾 {size}")
    updated = mod.get("updated", "")
    if updated:
        meta_parts.append(f"📅 {updated}")
    if tag_str:
        meta_parts.append(f"🏷 {tag_str}")
    if category and category != _DEFAULT_CATEGORY:
        meta_parts.insert(0, category)
    if meta_parts:
        parts.append(" ".join(meta_parts))

    # ── Ссылка ──
    parts.append("")
    parts.append(f'🔗 <a href="{mod["url"]}">Steam Workshop</a>')

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
    notify_chat_ids: list | None = None,
    telegram_bot_token: str = "",
):
    """Основной цикл монитора Steam Workshop.

    Контент идёт через модерацию:
      1. Сохраняется в БД как сообщение (source_type='workshop')
      2. Отправляется на веб-панель для модерации
      3. Публикуется в Telegram ТОЛЬКО после одобрения на панели
    """
    logger.info(
        "[WS] Steam Workshop Monitor запущен (интервал: %d сек / %.1f ч, мин. подписчиков: %d, AI: %s)",
        check_interval, check_interval / 3600, min_subscriptions,
        "вкл" if (ai_analyze and ai_analyzer) else "выкл",
    )
    stats.ensure_monitor("workshop", "Steam Workshop", "\U0001F527")
    stats.set_status("workshop", "active", "монитор запущен")

    # При старте — проверяем last_check, не парсим если рано
    state = _load_state()
    last_check = state.get("last_check")
    if last_check:
        try:
            last_ts = datetime.fromisoformat(last_check).timestamp()
            elapsed = time.time() - last_ts
            if elapsed < check_interval:
                remaining = check_interval - elapsed
                logger.info(
                    "[WS] С последней проверки прошло %.0f мин (интервал: %.0f мин) — ждём %.0f мин",
                    elapsed / 60, check_interval / 60, remaining / 60,
                )
                stats.set_status("workshop", "idle", f"следующая проверка через {remaining/60:.0f} мин")
                await asyncio.sleep(remaining)
        except (ValueError, TypeError):
            pass

    while True:
        cycle_start = time.time()
        mods_found = 0
        mods_processed = 0
        mods_published = 0
        cycle_errors = 0

        try:
            check_num = stats.get("workshop").get("checks", 0) + 1
            logger.info("[WS] ═══ Начало цикла проверки #%d ═══", check_num)
            stats.set_status("workshop", "checking", "поиск новых модов...")

            new_mods = await check_for_new_mods(
                steam_api_key=steam_api_key,
                min_subscriptions=min_subscriptions,
                days_old=30,
            )
            mods_found = len(new_mods)
            logger.info("[WS] Найдено новых модов: %d", mods_found)

            # Резолвим имена авторов
            if new_mods:
                logger.info("[WS] Резолвинг имён авторов для %d модов...", len(new_mods))
                await _resolve_author_names(new_mods)
                resolved = sum(1 for m in new_mods if m.get("author_name"))
                logger.info("[WS] Имена авторов: резолвено %d из %d", resolved, len(new_mods))

            for i, mod in enumerate(new_mods, 1):
                try:
                    subs = mod.get("subscriptions", 0)
                    favs = mod.get("favorited", 0)
                    views = mod.get("views", 0)
                    logger.info(
                        "[WS] Мод %d/%d: '%s' (ID: %s) | подписчиков: %d | избрано: %d | просмотров: %d",
                        i, len(new_mods), mod.get("title", "?")[:60], mod["id"], subs, favs, views,
                    )

                    ai_summary = None
                    if ai_analyze and ai_analyzer:
                        logger.info("[WS]   → AI анализ мода '%s'...", mod.get("title", "?")[:40])
                        try:
                            ai_summary = await ai_analyzer.analyze_workshop_mod(mod)
                            logger.info("[WS]   → AI анализ: успешно (%d символов)", len(ai_summary) if ai_summary else 0)
                        except Exception as e:
                            cycle_errors += 1
                            logger.error("[WS]   → AI анализ мода %s не удался: %s", mod["id"], e)
                    elif ai_analyze:
                        try:
                            from ai_analyzer import analyze_workshop_mod
                            ai_summary = await analyze_workshop_mod(mod)
                            logger.info("[WS]   → AI анализ (fallback): успешно")
                        except Exception as e:
                            cycle_errors += 1
                            logger.error("[WS]   → AI анализ (fallback) мода %s не удался: %s", mod["id"], e)

                    msg = format_mod_message(mod, ai_summary)
                    mods_processed += 1

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
                                news_type = "mod_update"
                                priority = "medium"
                                summary = ai_summary or ""
                                formatted_post = msg.get("text", "")

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
                                    "[WS]   → БД: мод '%s' #%d сохранён (type=%s, priority=%s)",
                                    mod["title"][:40], msg_id, news_type, priority,
                                )
                        except Exception as e:
                            cycle_errors += 1
                            logger.error("[WS]   → БД: ошибка сохранения мода %s: %s", mod["id"], e)

                    # Отправляем на веб-панель для модерации
                    if web_panel_url:
                        try:
                            from web_app_integration import send_to_web_panel
                            success = await send_to_web_panel(
                                news_data={
                                    "sourceId": "workshop",
                                    "externalId": mod["id"],
                                    "serverName": "Steam Workshop",
                                    "content": mod.get("description", "") or mod.get("title", ""),
                                    "summary": ai_summary or "",
                                    "formattedPost": msg.get("text", ""),
                                    "newsType": "mod_update",
                                    "priority": "medium",
                                    "images": [mod.get("image_url")] if mod.get("image_url") else [],
                                },
                                web_app_url=web_panel_url,
                                bot_api_key=web_panel_api_key or None,
                            )
                            if success:
                                mods_published += 1
                                logger.info("[WS]   → Панель: мод '%s' отправлен на модерацию", mod["title"][:40])
                                if notify_chat_ids and telegram_bot_token:
                                    try:
                                        from web_app_integration import notify_moderation
                                        await notify_moderation(
                                            title=ai_summary or mod.get("title", "")[:80],
                                            news_type="mod_update",
                                            priority="medium",
                                            source="Steam Workshop",
                                            notify_chat_ids=notify_chat_ids,
                                            bot_token=telegram_bot_token,
                                            web_panel_url=web_panel_url,
                                        )
                                    except Exception as notify_err:
                                        logger.warning("[WS]   → Уведомление о модерации: %s", notify_err)
                            else:
                                cycle_errors += 1
                                logger.error("[WS]   → Панель: ошибка отправки мода '%s'", mod["title"][:40])
                        except ImportError:
                            logger.warning("[WS]   → web_app_integration не найден — модерация через панель недоступна")
                        except Exception as e:
                            cycle_errors += 1
                            logger.error("[WS]   → Панель: исключение при отправке: %s", e)
                    elif not saved_to_db:
                        if telegram_bot:
                            await telegram_bot.send_workshop_post(msg)
                            mods_published += 1
                            logger.info("[WS]   → Telegram: мод '%s' опубликован напрямую (без модерации)", mod["title"][:40])

                    # Отмечаем как отправленный в state
                    state = _load_state()
                    if mod["id"] not in state.get("posted_ids", []):
                        state["posted_ids"].append(mod["id"])
                        _save_state(state)

                except Exception as e:
                    cycle_errors += 1
                    logger.error("[WS]   → Ошибка обработки мода %s: %s", mod.get("id", "unknown"), e)

                await asyncio.sleep(5)

        except Exception as e:
            cycle_errors += 1
            logger.error("[WS] Ошибка в цикле проверки: %s", e)

        # Записываем статистику цикла
        cycle_time = time.time() - cycle_start
        stats.record_check(
            "workshop",
            found=mods_found,
            processed=mods_processed,
            published=mods_published,
            errors=cycle_errors,
        )

        logger.info(
            "[WS] ═══ Конец цикла #%d: найдено=%d, обработано=%d, на модерации=%d, ошибки=%d, время=%.1fс ═══",
            check_num, mods_found, mods_processed, mods_published, cycle_errors, cycle_time,
        )

        if cycle_errors > 0:
            stats.set_status("workshop", "error", f"{cycle_errors} ошибок в последнем цикле")
        elif mods_published > 0:
            stats.set_status("workshop", "active", f"отправлено {mods_published} модов на модерацию")
        else:
            stats.set_status("workshop", "idle", f"следующая проверка через {check_interval/60:.0f} мин")

        logger.info("[WS] Следующая проверка через %d секунд (%.1f мин)...", check_interval, check_interval / 60)
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
