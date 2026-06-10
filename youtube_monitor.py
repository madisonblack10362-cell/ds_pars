"""
Модуль мониторинга YouTube для DayZ News Monitor.
Ищет короткие видео (shorts/рилс) по DayZ тематике через три бэкенда:
  1. Invidious API (динамическое обнаружение инстансов + статический фоллбэк)
  2. yt-dlp Python библиотека
  3. yt-dlp subprocess (последний resort)

Скачивает видео, анализирует через AI, публикует в Telegram.
"""

import asyncio
import json
import os
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiohttp

from logger import logger

# ─── Константы ─────────────────────────────────────────────────────────────

# Пороги длительности (секунды)
_LONG_VIDEO_MAX = 300        # > 5 минут — фильтруем
_SHORTS_MAX_DURATION = 90    # Порог для "шортс"

# Минимум кириллических символов для определения русского текста
_MIN_RU_CHARS = 3

# Путь к файлу состояния
_STATE_FILE = "youtube_state.json"

# Пул потоков для синхронных операций (yt-dlp, subprocess)
_thread_pool = ThreadPoolExecutor(max_workers=3)

# ─── Поисковые запросы — только короткий контент для Telegram канала ──────
_SEARCH_QUERIES = [
    ("DayZ шортс", "relevance", "week"),
    ("DayZ рилс", "relevance", "week"),
    ("DayZ shorts", "relevance", "week"),
    ("DayZ приколы", "relevance", "week"),
    ("DayZ баг", "relevance", "week"),
    ("DayZ мем", "relevance", "week"),
    ("DayZ фича", "relevance", "week"),
    ("DayZ секрет", "relevance", "week"),
    ("DayZ обновление", "relevance", "week"),
    ("DayZ патч", "relevance", "month"),
]

# ─── Категории контента ─────────────────────────────────────────────────────
_CATEGORY_KEYWORDS = {
    "guide": [
        "гайд", "гайды", "как", "how to", "tutorial", "инструкция",
        "обзор", "review", "использование", "использовать",
        "крафт", "craft", "loot", "лут", "спавн", "spawn",
    ],
    "pvp": [
        "pvp", "пвп", "fight", "бой", "битва", "рейд", "raid",
        "амбуш", "ambush", "нападение", "атака", "убийство", "kill",
        "победа", "win", "combat", "камп", "camp",
    ],
    "weapons": [
        "оружие", "weapon", "gun", "пушка", "винтовка", "rifle",
        "пистолет", "pistol", "штурмовая", "assault", "дробовик",
        "shotgun", "снайперская", "sniper", "аммо", "ammo", "патроны",
    ],
    "vehicles": [
        "машина", "car", "транспорт", "vehicle", "вертолёт", "helicopter",
        "вертушка", "лодка", "boat", "велосипед", "байк", "bus",
    ],
    "base": [
        "база", "base", "строительство", "building", "стройка",
        "хаус", "house", "ферма", "farm", "укрытие", "shelter",
        "банкрутка", "банкрут",
    ],
    "bugs": [
        "баг", "bug", "глюк", "glitch", "exploit", "эксплойт",
        "дюп", "dup", "cheat", "чит", "хак", "hack",
    ],
    "updates": [
        "обновление", "update", "патч", "patch", "патчноут",
        "новое", "new", "версия", "version", "выход", "release",
    ],
    "events": [
        "ивент", "event", "событие", "турнир", "tournament",
        "конкурс", "contest", "вайп", "wipe",
    ],
    "memes": [
        "мем", "meme", "прикол", "фан", "fan", "смешн", "funny",
        "ржака", "лол", "lol", "кринж", "cringe", "shitpost",
    ],
    "secrets": [
        "секрет", "secret", "пасхалка", "easter egg", "скрытое",
        "hidden", "тайна", "неизвестн", "unknown", " Easter",
    ],
}

# ─── Мусор-фильтры для стримов ─────────────────────────────────────────────
_STREAM_GARBAGE_PATTERNS = re.compile(
    r"(?i)"
    r"стрим\s*№\s*\d|"
    r"стрим\s*#\s*\d|"
    r"stream\s*#?\s*\d|"
    r"live\s*#?\s*\d|"
    r"пост-вайп|"
    r"post.?wipe|"
    r"PVE\s*проект|"
    r"PVP\s*проект|"
    r"►►|"
    r"▶▶|"
    r"donationalerts|"
    r"donate\s*alert|"
    r"поддержи\s*стрим|"
    r"click\s*here\s*to\s*subscribe|"
    r"ссылка\s*на\s*донат|"
    r"делай\s*ставку|"
    r"bet\s*now|"
    r"промокод|"
    r"скидка\s*\d+%|"
    r"играй\s*бесплатно",
    re.UNICODE,
)

# ─── Список релевантных ключевых слов контента ───────────────────────────────
_CONTENT_RELEVANT_KEYWORDS = [
    "гайд", "обзор", "pvp", "оружие", "винтовка", "пистолет", "дробовик",
    "штурмовая", "снайперская", "патроны", "аммо", "база", "строительство",
    "баг", "глюк", "exploit", "эксплойт", "чит", "хак", "обновление",
    "патч", "новое", "фича", "секрет", "пасхалка", "ивент", "турнир",
    "вайп", "мем", "прикол", "машин", "вертолёт", "лодка", "транспорт",
    "крафт", "лут", "спавн", "карта", "чере", "мод", "скрипт",
    "сервер", "настройк", "чистк", "рейд", "камп", "бой", "битва",
    "ambient", "zombie", "infected", "loot", "survival",
    "base building", "hideout", "tent", "stash",
    "kill", "combat", "ambush", "raid", "snipe",
    "patch", "update", "wipe", "event", "tournament",
    "guide", "tutorial", "tips", "trick", "secret", "hidden",
    "weapon", "gun", "rifle", "shotgun", "pistol", "ammo",
    "vehicle", "car", "helicopter", "boat", "bike",
    "bug", "glitch", "exploit", "cheat", "hack",
    "meme", "funny", "cringe", "shitpost",
]

# ─── Статические Invidious инстансы (фоллбэк) ──────────────────────────────
_STATIC_INVIDIOUS_INSTANCES = [
    "https://inv.tux.pizza",
    "https://invidious.nerdvpn.de",
    "https://invidious.jing.rocks",
    "https://invidious.lunar.icu",
    "https://inv.nadeko.net",
    "https://iv.datura.network",
    "https://invidious.privacyredirect.com",
    "https://invidious.protokolla.fi",
    "https://yt.cdaut.de",
    "https://invidious.perennialte.ch",
]

# ─── Кэш динамических инстансов ────────────────────────────────────────────
_dynamic_instances: list[str] = []
_dynamic_instances_timestamp: float = 0.0
_DYNAMIC_CACHE_TTL = 6 * 3600  # 6 часов


# ═════════════════════════════════════════════════════════════════════════════
#  Утилитные функции
# ═════════════════════════════════════════════════════════════════════════════

def _detect_category(title: str, description: str = "") -> str:
    """
    Определяет категорию видео по ключевым словам в заголовке и описании.
    Возвращает ключ категории или 'other'.
    """
    text = f"{title} {description}".lower()
    best_category = "other"
    best_count = 0

    for category, keywords in _CATEGORY_KEYWORDS.items():
        count = sum(1 for kw in keywords if kw.lower() in text)
        if count > best_count:
            best_count = count
            best_category = category

    return best_category


def _format_duration(seconds: int | float) -> str:
    """Форматирует длительность в читаемый вид (MM:SS или HH:MM:SS)."""
    if not seconds or seconds <= 0:
        return "0:00"
    seconds = int(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _format_views(views: int) -> str:
    """Форматирует число просмотров в читаемый вид."""
    if views >= 1_000_000:
        return f"{views / 1_000_000:.1f}M"
    if views >= 1_000:
        return f"{views / 1_000:.1f}K"
    return str(views)


def _escape_html(text: str) -> str:
    """Экранирует HTML-спецсимволы для Telegram."""
    if not text:
        return ""
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    text = text.replace('"', "&quot;")
    return text


def _parse_iso_duration(iso_duration: str) -> int:
    """
    Парсит ISO 8601 длительность (PT#M#S) в секунды.
    Пример: 'PT3M45S' → 225
    """
    if not iso_duration:
        return 0
    match = re.match(
        r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso_duration
    )
    if not match:
        return 0
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


def _is_russian_text(text: str) -> bool:
    """
    Проверяет, содержит ли текст минимум _MIN_RU_CHARS кириллических символов.
    """
    if not text:
        return False
    cyrillic_count = sum(1 for c in text if "\u0400" <= c <= "\u04FF")
    return cyrillic_count >= _MIN_RU_CHARS


def _is_stream_garbage(title: str) -> bool:
    """
    Проверяет, является ли видео мусорным стримом.
    Возвращает True если мусор.
    """
    if not title:
        return False
    return bool(_STREAM_GARBAGE_PATTERNS.search(title))


def _is_content_relevant(title: str, description: str = "") -> bool:
    """
    Проверяет, содержит ли контент релевантные ключевые слова DayZ.
    """
    text = f"{title} {description}".lower()
    return any(kw.lower() in text for kw in _CONTENT_RELEVANT_KEYWORDS)


def _parse_invidious_item(item: dict) -> dict:
    """
    Преобразует элемент из ответа Invidious API в унифицированный формат видео.
    """
    duration = item.get("lengthSeconds", 0) or 0
    if isinstance(duration, str):
        try:
            duration = int(duration)
        except (ValueError, TypeError):
            duration = 0

    views = item.get("viewCount", 0) or 0
    if isinstance(views, str):
        try:
            views = int(views.replace(",", ""))
        except (ValueError, TypeError):
            views = 0

    likes = item.get("likes", 0) or 0
    if isinstance(likes, str):
        try:
            likes = int(likes.replace(",", ""))
        except (ValueError, TypeError):
            likes = 0

    return {
        "video_id": item.get("videoId", ""),
        "title": (item.get("title") or "").strip(),
        "channel_title": (item.get("author") or "").strip(),
        "channel_id": item.get("authorId", ""),
        "duration": duration,
        "views": views,
        "likes": likes,
        "published": item.get("published", 0) or 0,
        "description": (item.get("description") or "")[:1000],
        "thumbnail": item.get("videoThumbnails", [{}])[-1].get("url", "")
        if item.get("videoThumbnails") else "",
        "url": f"https://www.youtube.com/watch?v={item.get('videoId', '')}",
        "is_live": bool(item.get("liveNow", False)),
        "source": "invidious",
    }


def format_video_message(video: dict, category: str = "") -> str:
    """
    Форматирует информацию о видео в текст для Telegram.
    """
    title = _escape_html(video.get("title", "Без названия"))
    ch_title = _escape_html(video.get("channel_title", "YouTube"))
    duration = _format_duration(video.get("duration", 0))
    views = _format_views(video.get("views", 0))
    url = video.get("url", "")

    lines = [
        f"🎬 <b>{title}</b>",
        f"📺 {ch_title}",
        f"⏱ {duration}  👁 {views}",
    ]

    category_label = {
        "guide": "📖 Гайд",
        "pvp": "⚔️ PvP",
        "weapons": "🔫 Оружие",
        "vehicles": "🚗 Транспорт",
        "base": "🏗 База",
        "bugs": "🐛 Баг/Чит",
        "updates": "🔄 Обновление",
        "events": "🎉 Ивент",
        "memes": "😂 Мем",
        "secrets": "🔮 Секрет",
    }.get(category, "")

    if category_label:
        lines.append(f"🏷 {category_label}")

    lines.append(url)
    return "\n".join(lines)


def cleanup_old_downloads(
    downloads_dir: str = "downloads",
    max_age_hours: int = 48,
) -> int:
    """
    Удаляет старые скачанные видео из директории.
    Возвращает количество удалённых файлов.
    """
    if not os.path.isdir(downloads_dir):
        return 0

    now = time.time()
    max_age = max_age_hours * 3600
    removed = 0

    for filename in os.listdir(downloads_dir):
        filepath = os.path.join(downloads_dir, filename)
        if not os.path.isfile(filepath):
            continue
        try:
            if now - os.path.getmtime(filepath) > max_age:
                os.remove(filepath)
                removed += 1
        except OSError:
            continue

    if removed > 0:
        logger.info("YouTube: удалено %d старых файлов из %s", removed, downloads_dir)

    return removed


# ═════════════════════════════════════════════════════════════════════════════
#  Управление состоянием
# ═════════════════════════════════════════════════════════════════════════════

def _load_state() -> dict:
    """Загружает состояние из JSON-файла (posted_ids и т.д.)."""
    if not os.path.exists(_STATE_FILE):
        return {"posted_ids": {}, "last_check": 0}
    try:
        with open(_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "posted_ids" not in data:
            data["posted_ids"] = {}
        return data
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("YouTube: не удалось загрузить состояние: %s", e)
        return {"posted_ids": {}, "last_check": 0}


def _save_state(state: dict) -> None:
    """Сохраняет состояние в JSON-файл."""
    try:
        with open(_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.warning("YouTube: не удалось сохранить состояние: %s", e)


# ═════════════════════════════════════════════════════════════════════════════
#  Invidious бэкенд (Backend 1)
# ═════════════════════════════════════════════════════════════════════════════

async def _fetch_dynamic_instances() -> list[str]:
    """
    Загружает список доступных Invidious инстансов с api.invidious.io.
    Кэшируется на 6 часов. Возвращает список URL инстансов.
    """
    global _dynamic_instances, _dynamic_instances_timestamp

    now = time.time()
    if _dynamic_instances and (now - _dynamic_instances_timestamp) < _DYNAMIC_CACHE_TTL:
        return _dynamic_instances

    logger.info("YouTube: загрузка динамических Invidious инстансов...")

    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                "https://api.invidious.io/instances.json"
            ) as response:
                if response.status != 200:
                    logger.warning(
                        "YouTube: api.invidious.io вернул HTTP %d",
                        response.status,
                    )
                    return _dynamic_instances

                data = await response.json()
                instances = []

                # Формат: [[{"name": "api"}, {"uri": "...", "stats": {...}}, ...], ...]
                # Берём только рабочие инстансы с API
                for entry in data:
                    if not isinstance(entry, list) or len(entry) < 2:
                        continue
                    info = entry[1]
                    if not isinstance(info, dict):
                        continue

                    uri = info.get("uri", "")
                    if not uri or not uri.startswith("https://"):
                        continue

                    # Фильтруем: только инстансы с доступным API,
                    # неCloudflare-protected, с的类型 1 (http)
                    api_ok = info.get("type", "") in (1, "1", "https")
                    stats = info.get("stats", {})
                    if isinstance(stats, dict):
                        # Проверяем что инстанс не мёртв
                        status = stats.get("status", "")
                        if status and status != "ok":
                            continue

                    if api_ok:
                        instances.append(uri.rstrip("/"))

                if instances:
                    # Обновляем кэш через in-place мутацию (без global)
                    _dynamic_instances[:] = instances
                    _dynamic_instances_timestamp = now
                    logger.info(
                        "YouTube: загружено %d динамических Invidious инстансов",
                        len(instances),
                    )
                else:
                    logger.warning(
                        "YouTube: api.invidious.io вернул пустой список инстансов"
                    )

    except asyncio.TimeoutError:
        logger.warning("YouTube: таймаут загрузки Invidious инстансов")
    except Exception as e:
        logger.warning("YouTube: ошибка загрузки Invidious инстансов: %s", e)

    return _dynamic_instances


async def _get_invidious_instances() -> list[str]:
    """Возвращает объединённый список инстансов (динамические + статические)."""
    dynamic = await _fetch_dynamic_instances()
    all_instances = list(dynamic)
    for inst in _STATIC_INVIDIOUS_INSTANCES:
        if inst not in all_instances:
            all_instances.append(inst)
    return all_instances


def _remove_bad_instance(instance_url: str) -> None:
    """Удаляет неработающий инстанс из кэша."""
    _dynamic_instances[:] = [
        inst for inst in _dynamic_instances
        if inst != instance_url
    ]


async def _search_invidious(
    query: str,
    sort_by: str = "relevance",
    date: str = "week",
    max_results: int = 10,
) -> list[dict]:
    """
    Ищет видео через Invidious API.
    Перебирает инстансы, автоматически исключает нерабочие.
    """
    instances = await _get_invidious_instances()
    timeout = aiohttp.ClientTimeout(total=10)

    for instance in instances:
        try:
            params = {
                "q": query,
                "sort_by": sort_by,
                "type": "video",
                "date": date,
                "page": 1,
            }

            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(
                    f"{instance}/api/v1/search",
                    params=params,
                ) as response:
                    if response.status != 200:
                        _remove_bad_instance(instance)
                        continue

                    items = await response.json()
                    results = []

                    for item in items:
                        if item.get("type") == "video":
                            video = _parse_invidious_item(item)
                            if video.get("video_id"):
                                results.append(video)
                            if len(results) >= max_results:
                                break

                    if results:
                        logger.debug(
                            "YouTube/Invidious: '%s' → %d результатов через %s",
                            query, len(results), instance,
                        )
                        return results

        except asyncio.TimeoutError:
            logger.debug(
                "YouTube/Invidious: таймаут инстанса %s", instance
            )
            _remove_bad_instance(instance)
        except Exception as e:
            logger.debug(
                "YouTube/Invidious: ошибка инстанса %s: %s", instance, e
            )
            _remove_bad_instance(instance)

    logger.warning(
        "YouTube/Invidious: ни один инстанс не ответил для запроса '%s'",
        query,
    )
    return []


# ═════════════════════════════════════════════════════════════════════════════
#  yt-dlp бэкенд (Backend 2 — Python библиотека)
# ═════════════════════════════════════════════════════════════════════════════

def _search_ytdlp_sync(
    query: str,
    max_results: int = 10,
) -> list[dict]:
    """
    Ищет видео через yt-dlp (синхронная версия для run_in_executor).
    """
    try:
        import yt_dlp
    except ImportError:
        logger.warning("YouTube/yt-dlp: библиотека yt-dlp не установлена")
        return []

    # Подавляем yt-dlp логирование до CRITICAL
    yt_dlp.utils._YOUTUBEDL_SUPPRESS_WARNINGS = True
    logging_module = yt_dlp.utils.__dict__.get("logging")
    if logging_module:
        try:
            logging_module.getLogger("yt-dlp").setLevel(logging_module.CRITICAL)
        except Exception:
            pass

    ydl_opts = {
        "extract_flat": "in_playlist",
        "quiet": True,
        "no_warnings": True,
        "default_search": "ytsearch",
        "max_downloads": max_results,
        "ignoreerrors": True,
    }

    search_query = f"ytsearch{max_results}:{query}"

    results = []
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(search_query, download=False)

        if not info:
            return results

        entries = info.get("entries", []) or []
        for entry in entries:
            if not isinstance(entry, dict):
                continue

            video_id = entry.get("id", "")
            title = (entry.get("title") or "").strip()
            duration = entry.get("duration", 0) or 0
            if isinstance(duration, str):
                try:
                    duration = int(duration)
                except (ValueError, TypeError):
                    duration = 0

            uploader = (entry.get("uploader") or "").strip()
            view_count = entry.get("view_count") or 0
            if isinstance(view_count, str):
                try:
                    view_count = int(view_count.replace(",", ""))
                except (ValueError, TypeError):
                    view_count = 0
            like_count = entry.get("like_count") or 0
            if isinstance(like_count, str):
                try:
                    like_count = int(like_count.replace(",", ""))
                except (ValueError, TypeError):
                    like_count = 0

            description = (entry.get("description") or "")[:1000]
            thumbnail = entry.get("thumbnail") or ""
            url = entry.get("url") or f"https://www.youtube.com/watch?v={video_id}"

            if video_id and title:
                results.append({
                    "video_id": video_id,
                    "title": title,
                    "channel_title": uploader,
                    "channel_id": entry.get("channel_id", ""),
                    "duration": int(duration),
                    "views": int(view_count),
                    "likes": int(like_count),
                    "published": entry.get("timestamp", 0) or 0,
                    "description": description,
                    "thumbnail": thumbnail,
                    "url": url,
                    "is_live": bool(entry.get("is_live", False)),
                    "source": "yt_dlp",
                })

    except Exception as e:
        logger.warning("YouTube/yt-dlp: ошибка поиска '%s': %s", query, e)

    return results


async def _search_ytdlp(
    query: str,
    max_results: int = 10,
) -> list[dict]:
    """
    Ищет видео через yt-dlp Python библиотеку (асинхронная обёртка).
    Подавляет yt-dlp логирование до CRITICAL уровня.
    """
    import logging as _stdlib_logging

    # Подавляем yt-dlp логирование ГЛОБАЛЬНО до CRITICAL
    try:
        import yt_dlp
        _stdlib_logging.getLogger("yt-dlp").setLevel(_stdlib_logging.CRITICAL)
        _stdlib_logging.getLogger("yt_dlp").setLevel(_stdlib_logging.CRITICAL)
    except ImportError:
        return []

    loop = asyncio.get_running_loop()
    try:
        results = await loop.run_in_executor(
            _thread_pool,
            _search_ytdlp_sync,
            query,
            max_results,
        )
    except Exception as e:
        logger.warning("YouTube/yt-dlp: ошибка executor: %s", e)
        results = []

    if results:
        logger.debug(
            "YouTube/yt-dlp: '%s' → %d результатов", query, len(results)
        )
    return results


# ═════════════════════════════════════════════════════════════════════════════
#  yt-dlp subprocess бэкенд (Backend 3 — последний resort)
# ═════════════════════════════════════════════════════════════════════════════

def _search_ytdlp_subprocess_sync(
    query: str,
    max_results: int = 10,
) -> list[dict]:
    """
    Ищет видео через yt-dlp subprocess (последний resort).
    Парсит JSON output.
    """
    try:
        cmd = [
            "yt-dlp",
            "--dump-json",
            "--flat-playlist",
            "--playlist-end", str(max_results),
            "--no-download",
            f"ytsearch{max_results}:{query}",
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            stderr=subprocess.PIPE,
        )

        if result.returncode != 0:
            stderr = result.stderr[:500] if result.stderr else ""
            logger.debug(
                "YouTube/yt-dlp-subprocess: ошибка (rc=%d): %s",
                result.returncode, stderr,
            )
            return []

        videos = []
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            if not isinstance(entry, dict):
                continue

            video_id = entry.get("id", "")
            title = (entry.get("title") or "").strip()
            if not video_id or not title:
                continue

            duration = entry.get("duration", 0) or 0
            if isinstance(duration, str):
                try:
                    duration = int(duration)
                except (ValueError, TypeError):
                    duration = 0

            videos.append({
                "video_id": video_id,
                "title": title,
                "channel_title": (entry.get("uploader") or "").strip(),
                "channel_id": entry.get("channel_id", ""),
                "duration": int(duration),
                "views": 0,
                "likes": 0,
                "published": entry.get("timestamp", 0) or 0,
                "description": (entry.get("description") or "")[:1000],
                "thumbnail": entry.get("thumbnail") or "",
                "url": entry.get("url") or f"https://www.youtube.com/watch?v={video_id}",
                "is_live": False,
                "source": "yt_dlp_subprocess",
            })

        return videos

    except FileNotFoundError:
        logger.warning("YouTube/yt-dlp-subprocess: yt-dlp не найден в PATH")
        return []
    except subprocess.TimeoutExpired:
        logger.warning("YouTube/yt-dlp-subprocess: таймаут")
        return []
    except Exception as e:
        logger.warning("YouTube/yt-dlp-subprocess: ошибка: %s", e)
        return []


async def _search_ytdlp_subprocess(
    query: str,
    max_results: int = 10,
) -> list[dict]:
    """
    Ищет видео через yt-dlp subprocess (асинхронная обёртка).
    """
    loop = asyncio.get_running_loop()
    try:
        results = await loop.run_in_executor(
            _thread_pool,
            _search_ytdlp_subprocess_sync,
            query,
            max_results,
        )
    except Exception as e:
        logger.warning("YouTube/yt-dlp-subprocess: ошибка executor: %s", e)
        results = []

    if results:
        logger.debug(
            "YouTube/yt-dlp-subprocess: '%s' → %d результатов",
            query, len(results),
        )
    return results


# ═════════════════════════════════════════════════════════════════════════════
#  Объединённый поиск (триггер бэкендов по очереди)
# ═════════════════════════════════════════════════════════════════════════════

async def _search_videos(
    query: str,
    sort_by: str = "relevance",
    date_filter: str = "week",
    max_results: int = 10,
) -> list[dict]:
    """
    Ищет видео через три бэкенда по очереди.
    Возвращает результаты первого успешного бэкенда.
    """
    # Backend 1: Invidious
    results = await _search_invidious(
        query=query,
        sort_by=sort_by,
        date=date_filter,
        max_results=max_results,
    )
    if results:
        return results

    logger.info(
        "YouTube: Invidious не ответил, пробуем yt-dlp Python для '%s'",
        query,
    )

    # Backend 2: yt-dlp Python
    results = await _search_ytdlp(query=query, max_results=max_results)
    if results:
        return results

    logger.info(
        "YouTube: yt-dlp Python не ответил, пробуем yt-dlp subprocess для '%s'",
        query,
    )

    # Backend 3: yt-dlp subprocess
    results = await _search_ytdlp_subprocess(
        query=query, max_results=max_results
    )
    if results:
        return results

    logger.warning("YouTube: все бэкенды не ответили для запроса '%s'", query)
    return []


# ═════════════════════════════════════════════════════════════════════════════
#  Скачивание видео
# ═════════════════════════════════════════════════════════════════════════════

def _download_ytdlp_sync(
    url: str,
    output_template: str,
    cookies_file: str = "",
    cookies_browser: str = "",
    max_filesize: int = 50 * 1024 * 1024,
) -> str | None:
    """
    Скачивает видео через yt-dlp (синхронная для run_in_executor).
    Возвращает путь к файлу или None.
    """
    import logging as _stdlib_logging

    # Подавляем yt-dlp логирование
    _stdlib_logging.getLogger("yt-dlp").setLevel(_stdlib_logging.CRITICAL)
    _stdlib_logging.getLogger("yt_dlp").setLevel(_stdlib_logging.CRITICAL)

    try:
        import yt_dlp
    except ImportError:
        logger.error("YouTube/download: yt-dlp не установлен")
        return None

    ydl_opts = {
        "format": (
            "best[filesize<50M]"
            "/best[height<=720][filesize<50M]"
            "/best[height<=480]"
            "/worst"
        ),
        "outtmpl": output_template,
        "max_filesize": max_filesize,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "nocheckcertificate": True,
    }

    if cookies_file and os.path.isfile(cookies_file):
        ydl_opts["cookiefile"] = cookies_file
    elif cookies_browser:
        ydl_opts["cookiesfrombrowser"] = cookies_browser

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        if info:
            filepath = info.get("requested_downloads", [{}])
            if filepath:
                return filepath[0].get("filepath") or None
            # Фоллбэк: определяем путь через outtmpl
            video_id = info.get("id", "unknown")
            return output_template.replace("%(id)s", video_id)
    except Exception as e:
        logger.debug("YouTube/download: yt-dlp ошибка: %s", e)

    return None


async def download_short(
    video: dict,
    downloads_dir: str = "downloads",
    max_filesize_mb: int = 50,
) -> str | None:
    """
    Скачивает короткое видео с YouTube с поддержкой cookies.

    Стратегия cookies:
      1. Проверяет cookies.txt рядом со скриптом
      2. Пробует --cookies-from-browser (chrome/edge/brave/firefox)
      3. Без cookies

    Каждая попытка с браузером — полноценная попытка скачивания.
    При успехе — немедленный возврат.

    Returns:
        Путь к скачанному файлу или None.
    """
    url = video.get("url", "")
    video_id = video.get("video_id", "unknown")
    if not url:
        return None

    os.makedirs(downloads_dir, exist_ok=True)
    output_template = os.path.join(downloads_dir, "%(id)s.%(ext)s")
    max_filesize = max_filesize_mb * 1024 * 1024

    # ─── Попытка 1: cookies.txt рядом со скриптом ─────────────────────────
    script_dir = os.path.dirname(os.path.abspath(__file__))
    cookies_path = os.path.join(script_dir, "cookies.txt")

    if os.path.isfile(cookies_path):
        logger.debug("YouTube/download: используем cookies.txt")
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            _thread_pool,
            _download_ytdlp_sync,
            url,
            output_template,
            cookies_path,
            "",
            max_filesize,
        )
        if result and os.path.isfile(result):
            logger.info("YouTube/download: скачано через cookies.txt → %s", result)
            return result

    # ─── Попытка 2-5: --cookies-from-browser ─────────────────────────────
    import sys
    platform = sys.platform.lower()
    browsers = []
    if platform.startswith("win"):
        browsers = ["chrome", "edge", "brave", "firefox"]
    elif platform.startswith("darwin"):
        browsers = ["chrome", "firefox", "safari"]
    else:
        browsers = ["chrome", "firefox", "brave"]

    for browser in browsers:
        logger.debug("YouTube/download: пробуем cookies из браузера '%s'", browser)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            _thread_pool,
            _download_ytdlp_sync,
            url,
            output_template,
            "",
            browser,
            max_filesize,
        )
        if result and os.path.isfile(result):
            logger.info(
                "YouTube/download: скачано через %s cookies → %s",
                browser, result,
            )
            return result

    # ─── Попытка последняя: без cookies ──────────────────────────────────
    logger.debug("YouTube/download: пробуем без cookies")
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        _thread_pool,
        _download_ytdlp_sync,
        url,
        output_template,
        "",
        "",
        max_filesize,
    )
    if result and os.path.isfile(result):
        logger.info("YouTube/download: скачано без cookies → %s", result)
        return result

    logger.warning("YouTube/download: не удалось скачать '%s' (%s)", url, video_id)
    return None


# ═════════════════════════════════════════════════════════════════════════════
#  Фильтрация контента
# ═════════════════════════════════════════════════════════════════════════════

def _filter_video(
    video: dict,
    min_views: int = 0,
    min_likes: int = 0,
) -> bool:
    """
    Фильтрует видео. Возвращает True если видео проходит фильтры.

    Фильтры:
      - Длительность (не более _LONG_VIDEO_MAX секунд)
      - Не прямой эфир
      - Не мусорный стрим
      - Релевантность контента (контентные ключевые слова)
      - Просмотров/лайки (SKIP если views=0 — yt-dlp fallback без статы)
      - Русский язык (3+ кириллических символа)
    """
    # Пропускаем прямые эфиры
    if video.get("is_live", False):
        return False

    # Фильтр длительности: > 5 минут — мусор для shorts канала
    duration = video.get("duration", 0) or 0
    if duration > _LONG_VIDEO_MAX:
        return False

    # Фильтр мусорных стримов
    title = video.get("title", "")
    if _is_stream_garbage(title):
        return False

    # Фильтр релевантности контента
    description = video.get("description", "")
    if not _is_content_relevant(title, description):
        return False

    # Фильтр просмотров/лайков — SKIP когда views=0
    # (yt-dlp fallback в flat mode не имеет статистики)
    views = video.get("views", 0) or 0
    likes = video.get("likes", 0) or 0

    if views > 0:
        if min_views > 0 and views < min_views:
            return False
        if min_likes > 0 and likes < min_likes:
            return False

    # Фильтр русского языка
    text_to_check = f"{title} {description}"
    if not _is_russian_text(text_to_check):
        return False

    return True


# ═════════════════════════════════════════════════════════════════════════════
#  Основная логика мониторинга
# ═════════════════════════════════════════════════════════════════════════════

async def check_for_new_videos(
    db=None,
    config: dict | None = None,
    web_panel_url: str = "",
    web_panel_api_key: str = "",
) -> list[dict]:
    """
    Проверяет YouTube на наличие новых DayZ видео по всем поисковым запросам.

    Args:
        db: Экземпляр Database для сохранения результатов.
        config: Словарь с настройками (min_views, min_likes, max_results и т.д.).
        web_panel_url: URL веб-панели для отправки новостей.
        web_panel_api_key: API ключ для авторизации на веб-панели.

    Returns:
        Список найденных новых видео (dict).
    """
    if config is None:
        config = {}

    # Безопасное извлечение конфигов с int() для JSON-значений
    min_views = int(config.get("youtube_min_views", 0))
    min_likes = int(config.get("youtube_min_likes", 0))
    max_per_check = int(config.get("youtube_max_per_check", 5))
    max_results = int(config.get("youtube_max_results", 10))

    state = _load_state()
    posted_ids = state.get("posted_ids", {})
    if not isinstance(posted_ids, dict):
        posted_ids = {}

    all_new_videos = []
    seen_video_ids = set()
    processed_count = 0

    for query, sort_by, date_filter in _SEARCH_QUERIES:
        if processed_count >= max_per_check:
            logger.info(
                "YouTube: достигнут лимит max_per_check=%d", max_per_check
            )
            break

        logger.info("YouTube: поиск '%s' (sort=%s, date=%s)", query, sort_by, date_filter)

        try:
            videos = await _search_videos(
                query=query,
                sort_by=sort_by,
                date_filter=date_filter,
                max_results=max_results,
            )
        except Exception as e:
            logger.error("YouTube: ошибка поиска '%s': %s", query, e)
            continue

        for video in videos:
            video_id = video.get("video_id", "")
            if not video_id:
                continue

            # Пропускаем дубликаты в рамках текущего check
            if video_id in seen_video_ids:
                continue
            seen_video_ids.add(video_id)

            # Пропускаем уже опубликованные
            if video_id in posted_ids:
                continue

            # Фильтруем
            if not _filter_video(video, min_views=min_views, min_likes=min_likes):
                continue

            # Определяем категорию
            category = _detect_category(
                video.get("title", ""),
                video.get("description", ""),
            )

            video["category"] = category
            all_new_videos.append(video)
            processed_count += 1

            # Отмечаем в состоянии
            posted_ids[video_id] = {
                "title": video.get("title", "")[:200],
                "timestamp": time.time(),
                "category": category,
            }

            logger.info(
                "YouTube: новое видео: %s (%s, %s, %s, %d просмотров)",
                video.get("title", "")[:60],
                video.get("channel_title", ""),
                _format_duration(video.get("duration", 0)),
                category,
                video.get("views", 0),
            )

    # Сохраняем состояние
    state["posted_ids"] = posted_ids
    state["last_check"] = time.time()
    _save_state(state)

    # ─── Сохраняем в БД и отправляем в веб-панель ────────────────────────
    if db and all_new_videos:
        await _save_videos_to_db(
            db=db,
            videos=all_new_videos,
            config=config,
            web_panel_url=web_panel_url,
            web_panel_api_key=web_panel_api_key,
        )

    if all_new_videos:
        logger.info("YouTube: всего найдено %d новых видео", len(all_new_videos))

    return all_new_videos


async def _save_videos_to_db(
    db,
    videos: list[dict],
    config: dict,
    web_panel_url: str = "",
    web_panel_api_key: str = "",
) -> None:
    """
    Сохраняет найденные видео в БД и отправляет на веб-панель.
    """
    downloads_dir = config.get("images_dir", "downloads")
    do_download = config.get("youtube_download", True)

    for video in videos:
        video_id = video.get("video_id", "")
        ch_title = video.get("channel_title", "YouTube")
        title = video.get("title", "Без названия")
        description = video.get("description", "")
        url = video.get("url", "")
        category = video.get("category", "other")

        # Форматируем сообщение
        msg = format_video_message(video, category=category)
        ai_summary = f"[{category}] {title}"

        # Регистрируем источник
        await db.register_source(
            source_type="youtube",
            server_name=ch_title,
            source_id="youtube_search",
            extra={"video_id": video_id, "category": category},
        )

        # Сохраняем сообщение
        msg_id = await db.save_message(
            external_id=f"yt_{video_id}",
            source_type="youtube",
            source_id="youtube_search",
            server_name=ch_title,
            text=msg,
            title=title,
            channel_name=ch_title,
            author=ch_title,
            images=[],
            links=[url],
            published_at_source=None,
        )

        if not msg_id:
            logger.debug(
                "YouTube: дубликат или ошибка сохранения: %s (%s)",
                video_id, title[:50],
            )
            continue

        # AI-анализ через ai_analyzer
        priority = "low"
        if category in ("updates", "events"):
            priority = "medium"
        elif category in ("secrets", "weapons", "bugs"):
            priority = "medium"

        # Пробуем AI-анализ
        try:
            from ai_analyzer import _get_analyzer
            analyzer = _get_analyzer()
            ai_result = await analyzer.analyze(
                text=f"{title}\n{description[:500]}",
                author=ch_title,
            )
            if ai_result:
                priority = ai_result.get("priority", priority)
                ai_summary = ai_result.get("summary", ai_summary) or ai_summary
        except Exception as e:
            logger.debug("YouTube: AI-анализ недоступен: %s", e)

        # Сохраняем результаты обработки
        await db.save_processed(
            message_id=msg_id,
            news_type=category,
            priority=priority,
            should_publish=False,
            summary=ai_summary or "",
            server_name=ch_title,
            formatted_post=msg.get("text", ""),
        )

        # Отправка на веб-панель
        if web_panel_url:
            try:
                from web_app_integration import send_to_web_panel
                await send_to_web_panel(
                    news_data={
                        "source_type": "youtube",
                        "source_id": "youtube_search",
                        "external_id": f"yt_{video_id}",
                        "title": title,
                        "content": msg,
                        "server_name": ch_title,
                        "news_type": category,
                        "priority": priority,
                        "url": url,
                        "thumbnail": video.get("thumbnail", ""),
                        "summary": ai_summary or "",
                    },
                    web_app_url=web_panel_url,
                    bot_api_key=web_panel_api_key or None,
                )
            except Exception as e:
                logger.debug("YouTube: ошибка отправки на веб-панель: %s", e)

        # Скачиваем видео (опционально)
        if do_download and video.get("duration", 0) <= _SHORTS_MAX_DURATION:
            try:
                filepath = await download_short(
                    video, downloads_dir=downloads_dir
                )
                if filepath:
                    logger.info(
                        "YouTube: видео скачано → %s (%.1f MB)",
                        filepath,
                        os.path.getsize(filepath) / (1024 * 1024),
                    )
            except Exception as e:
                logger.debug("YouTube: ошибка скачивания: %s", e)


# ═════════════════════════════════════════════════════════════════════════════
#  Постоянный мониторинг (фоновая задача)
# ═════════════════════════════════════════════════════════════════════════════

async def run_youtube_monitor(
    db=None,
    config: dict | None = None,
    web_panel_url: str = "",
    web_panel_api_key: str = "",
    notification_callback=None,
) -> None:
    """
    Запускает постоянный мониторинг YouTube в фоновом режиме.

    Args:
        db: Экземпляр Database.
        config: Словарь с настройками.
        web_panel_url: URL веб-панели.
        web_panel_api_key: API ключ для веб-панели.
        notification_callback: Асинхронная функция для уведомлений.
            Сигнатура: async def callback(video: dict) -> None
    """
    if config is None:
        config = {}

    # Безопасное извлечение конфигов с int() для JSON-значений
    check_interval_hours = int(config.get("youtube_check_interval_hours", 6))
    if check_interval_hours < 1:
        check_interval_hours = 1

    logger.info(
        "YouTube монитор: запущен (интервал=%d ч)", check_interval_hours
    )

    while True:
        try:
            start_time = time.time()
            logger.info("YouTube монитор: проверка...")

            new_videos = await check_for_new_videos(
                db=db,
                config=config,
                web_panel_url=web_panel_url,
                web_panel_api_key=web_panel_api_key,
            )

            # Уведомляем через callback
            if new_videos and notification_callback:
                for video in new_videos:
                    try:
                        await notification_callback(video)
                    except Exception as e:
                        ch_title = video.get("channel_title", "")
                        logger.debug(
                            "YouTube: ошибка callback для '%s': %s",
                            ch_title, e,
                        )

            # Убираем старые скачивания
            cleanup_old_downloads(
                downloads_dir=config.get("images_dir", "downloads"),
            )

            elapsed = time.time() - start_time
            logger.info(
                "YouTube монитор: проверка завершена за %.1f с "
                "(найдено %d новых видео)",
                elapsed, len(new_videos),
            )

        except Exception as e:
            logger.error("YouTube монитор: критическая ошибка: %s", e)

        # Ждём до следующей проверки
        await asyncio.sleep(check_interval_hours * 3600)


# ═════════════════════════════════════════════════════════════════════════════
#  Standalone запуск (для тестирования)
# ═════════════════════════════════════════════════════════════════════════════

async def main():
    """Standalone запуск YouTube монитора для тестирования."""
    import os
    import json

    config_path = os.environ.get("CONFIG_PATH", "config.json")
    config = {}
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except FileNotFoundError:
        logger.warning("config.json не найден, используем дефолтные настройки")

    logger.info("YouTube монитор: standalone режим")

    videos = await check_for_new_videos(
        db=None,
        config=config,
    )

    if videos:
        logger.info(
            "YouTube монитор: найдено %d видео в standalone режиме",
            len(videos),
        )
        for v in videos:
            print(format_video_message(v, v.get("category", "")))
            print("─" * 60)
    else:
        logger.info("YouTube монитор: новых видео не найдено")


if __name__ == "__main__":
    asyncio.run(main())
