"""
Модуль мониторинга YouTube для DayZ News Monitor.
Профессиональная система сбора актуального контента (шортсы, рилс, короткие видео)
по DayZ тематике.

Архитектура поиска (4 стратегии, параллельно):
  1. RSS-ленты каналов — прямой источник свежих видео через PubSubHubbub RSS
  2. YouTube Shorts RSS — шортсы из trending/недавних
  3. Invidious API — поиск с фильтром даты (week/month)
  4. yt-dlp — фоллбэк поиск без даты, с post-filter по timestamp

Фильтрация:
  - Длительность: shorts (< 90с) + короткие видео (< 5 мин)
  - Дата публикации: за последние N дней (конфигурируемое)
  - Релевантность: ключевые слова + AI-анализ
  - Качество: минимальные просмотры/лайки
  - Дедупликация: video_id → youtube_state.json + БД
"""

import asyncio
import hashlib
import json
import os
import re
import subprocess
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET

import aiohttp

from logger import logger

# ─── Константы ─────────────────────────────────────────────────────────────

# Пороги длительности (секунды)
_SHORTS_MAX_DURATION = 90    # Порог для "шортс" (YouTube Shorts)
_LONG_VIDEO_MAX = 600         # > 10 минут — не берём (DayZ гайды до 10 мин ок)

# Пороги даты
_DEFAULT_LOOKBACK_DAYS = 90   # По умолчанию ищем за 3 месяца

# Минимум кириллических символов для определения русского текста
_MIN_RU_CHARS = 2  # Смягчённый порог (было 3)

# Путь к файлу состояния
_STATE_FILE = "youtube_state.json"

# Пул потоков для синхронных операций (yt-dlp, subprocess)
_thread_pool = ThreadPoolExecutor(max_workers=4)

# User-Agent для HTTP запросов
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

# ─── Каналы DayZ для RSS мониторинга ─────────────────────────────────────────
# ID каналов YouTube — источники самого свежего контента
_YOUTUBE_CHANNELS = [
    # Русскоязычные DayZ каналы
    {"id": "UCrUjJxYKFkVRP4p32XZJTSw", "name": "DayZ Russia"},         # пример
    {"id": "UCvQPcPcEzzMPTjTMzGCRN0g", "name": "DayZ Official"},
    # Англоязычные — основной контент
    {"id": "UCCfHa1Yg2p_VMRxiGEPyOZw", "name": "DayZ"},               # можно заменить на реальные
    {"id": "UCpJRfKxOQoYeGkMwWObqfzg", "name": "DayZ Survivor"},
]

# ─── Поисковые запросы для API поиска ────────────────────────────────────────
# Расширенные запросы с целевыми ключевыми словами для шортсов
_SEARCH_QUERIES = [
    # Shorts-специфичные запросы
    ("DayZ shorts", "relevance"),
    ("DayZ шортс", "relevance"),
    ("DayZ рилс", "relevance"),
    ("DayZ funny moments", "relevance"),
    ("DayZ приколы", "relevance"),
    # Контентные запросы
    ("DayZ gameplay 2025", "date"),
    ("DayZ update", "date"),
    ("DayZ патч", "date"),
    ("DayZ баг glitch", "relevance"),
    ("DayZ pvp highlights", "relevance"),
    ("DayZ raid", "relevance"),
    ("DayZ base building", "relevance"),
    ("DayZ секрет пасхалка", "relevance"),
    ("DayZ мем", "relevance"),
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

# ─── Стрим-фильтры (любые упоминания стрима/лайва = мусор) ───────────
_STREAM_LIVE_KEYWORDS = re.compile(
    r"(?i)"
    r"\bstream\b|"
    r"\bstreams?\b|"
    r"\bстрим\b|"
    r"\bстримы\b|"
    r"\blive\b|"
    r"\bлайв\b|"
    r"\bтрансляци\b|"
    r"\bbroadcast\b",
    re.UNICODE,
)

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
    "dayz",  # Главное ключевое слово — должно быть в тексте
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
    "chernarus", "livonia", "sakit",
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

# ─── Кэш RSS для каналов (чтобы не спамить YouTube) ────────────────────────
_rss_cache_lock = threading.Lock()
_rss_cache: dict[str, str] = {}  # channel_id → etag/last_modified
_RSS_CHECK_INTERVAL = 300  # Минимум 5 минут между проверками канала


# ═════════════════════════════════════════════════════════════════════════════
#  Утилитные функции
# ═════════════════════════════════════════════════════════════════════════════

def _detect_category(title: str, description: str = "") -> str:
    """Определяет категорию видео по ключевым словам."""
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
    """Форматирует длительность в читаемый вид."""
    if not seconds or seconds <= 0:
        return "0:00"
    seconds = int(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _format_views(views: int) -> str:
    """Форматирует число просмотров."""
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


def _is_russian_text(text: str) -> bool:
    """Проверяет, содержит ли текст кириллические символы (смягчённый порог)."""
    if not text:
        return False
    cyrillic_count = sum(1 for c in text if "\u0400" <= c <= "\u04FF")
    return cyrillic_count >= _MIN_RU_CHARS


def _is_dayz_related(title: str, description: str = "") -> bool:
    """
    Проверяет, относится ли контент к DayZ.
    Смягчённая версия — достаточно 'dayz' в тексте ИЛИ 2+ релевантных ключевых слова.
    """
    text = f"{title} {description}".lower()
    # Если есть 'dayz' — точно релевантно
    if "dayz" in text:
        return True
    # Иначе проверяем количество других ключевых слов
    kw_count = sum(1 for kw in _CONTENT_RELEVANT_KEYWORDS if kw != "dayz" and kw.lower() in text)
    return kw_count >= 2


def _is_stream_garbage(title: str) -> bool:
    """Проверяет, является ли видео стримом/трансляцией — отсеиваем полностью."""
    if not title:
        return False
    # Любое упоминание stream/стрим/live в title = стрим
    if _STREAM_LIVE_KEYWORDS.search(title):
        return True
    return bool(_STREAM_GARBAGE_PATTERNS.search(title))


def _is_within_lookback(published_ts: int | float, lookback_days: int) -> bool:
    """
    Проверяет, находится ли видео в диапазоне lookback_days от текущей даты.
    published_ts — Unix timestamp.
    """
    if not published_ts or published_ts <= 0:
        return True  # Если нет даты — не фильтруем (даём шанс)
    cutoff = time.time() - (lookback_days * 86400)
    return published_ts >= cutoff


def _parse_rfc2822_date(date_str: str) -> float:
    """Парсит RFC 2822 дату в Unix timestamp."""
    if not date_str:
        return 0
    try:
        dt = parsedate_to_datetime(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return 0


def _parse_iso8601_duration(iso_duration: str) -> int:
    """Парсит ISO 8601 длительность (PT#M#S) в секунды."""
    if not iso_duration:
        return 0
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso_duration)
    if not match:
        return 0
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


def format_video_message(video: dict, category: str = "") -> str:
    """Форматирует информацию о видео в текст для Telegram."""
    title = _escape_html(video.get("title", "Без названия"))
    ch_title = _escape_html(video.get("channel_title", "YouTube"))
    duration = _format_duration(video.get("duration", 0))
    views = _format_views(video.get("views", 0))
    url = video.get("url", "")

    # Определяем тип контента
    dur = video.get("duration", 0) or 0
    if dur <= _SHORTS_MAX_DURATION:
        content_type = "📱 Shorts"
    elif dur <= 180:
        content_type = "🎬 Видео"
    else:
        content_type = "📹 Длинное"

    lines = [
        f"{content_type} <b>{title}</b>",
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
    """Удаляет старые скачанные видео."""
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
    """Загружает состояние из JSON-файла."""
    if not os.path.exists(_STATE_FILE):
        return {"posted_ids": {}, "last_check": 0, "channel_etags": {}}
    try:
        with open(_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "posted_ids" not in data:
            data["posted_ids"] = {}
        if "channel_etags" not in data:
            data["channel_etags"] = {}
        return data
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("YouTube: не удалось загрузить состояние: %s", e)
        return {"posted_ids": {}, "last_check": 0, "channel_etags": {}}


def _save_state(state: dict) -> None:
    """Сохраняет состояние в JSON-файл."""
    try:
        with open(_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.warning("YouTube: не удалось сохранить состояние: %s", e)


# ═════════════════════════════════════════════════════════════════════════════
#  Стратегия 1: RSS-ленты каналов (прямой источник)
# ═════════════════════════════════════════════════════════════════════════════

def _parse_rss_entry(entry: ET.Element) -> dict | None:
    """
    Парсит один <entry> из YouTube RSS/Atom фида в унифицированный формат.
    """
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "yt": "http://www.youtube.com/xml/schemas/2015",
        "media": "http://search.yahoo.com/mrss/",
    }

    # Video ID
    video_id = ""
    video_url = entry.find("atom:link", ns)
    if video_url is not None:
        href = video_url.get("href", "")
        # YouTube RSS даёт URL вида https://www.youtube.com/watch?v=XXXXX
        match = re.search(r"v=([a-zA-Z0-9_-]+)", href)
        if match:
            video_id = match.group(1)

    if not video_id:
        return None

    # Title
    title_el = entry.find("atom:title", ns)
    title = title_el.text.strip() if title_el is not None and title_el.text else ""

    # Channel
    channel_el = entry.find("atom:author/atom:name", ns)
    channel_title = channel_el.text.strip() if channel_el is not None and channel_el.text else ""

    # Published date
    published = 0
    published_el = entry.find("atom:published", ns)
    if published_el is not None and published_el.text:
        published = _parse_rfc2822_date(published_el.text)

    # Updated date (fallback)
    updated = 0
    updated_el = entry.find("atom:updated", ns)
    if updated_el is not None and updated_el.text:
        updated = _parse_rfc2822_date(updated_el.text)

    # Duration (из yt:duration или media:group/media:content)
    duration = 0
    group = entry.find("media:group", ns)
    if group is not None:
        dur_el = group.find("yt:duration", ns)
        if dur_el is not None:
            dur_str = dur_el.get("seconds", "0")
            try:
                duration = int(dur_str)
            except (ValueError, TypeError):
                duration = 0

        # Views
        views_el = group.find("media:community/media:statistics", ns)
        if views_el is not None:
            try:
                views = int(views_el.get("views", "0"))
            except (ValueError, TypeError):
                views = 0
        else:
            views = 0

        # Likes
        likes_el = group.find("media:community/media:starRating", ns)
        likes = 0
        if likes_el is not None:
            try:
                likes = int(likes_el.get("count", "0"))
            except (ValueError, TypeError):
                likes = 0

        # Thumbnail
        thumb_el = group.find("media:thumbnail", ns)
        thumbnail = thumb_el.get("url", "") if thumb_el is not None else ""
    else:
        views = 0
        likes = 0
        thumbnail = ""

    # Description
    desc_el = group.find("media:description", ns) if group is not None else None
    description = ""
    if desc_el is not None and desc_el.text:
        description = desc_el.text[:1000]

    if not published and updated:
        published = updated

    return {
        "video_id": video_id,
        "title": title,
        "channel_title": channel_title,
        "channel_id": "",
        "duration": duration,
        "views": views,
        "likes": likes,
        "published": published,
        "description": description,
        "thumbnail": thumbnail,
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "is_live": False,
        "source": "rss",
    }


async def _fetch_channel_rss(channel_id: str, etag: str = "") -> tuple[list[dict], str, str]:
    """
    Загружает RSS-ленту канала. Возвращает (videos, new_etag, last_modified).
    Использует Conditional GET (If-None-Match / If-Modified-Since) для кэширования.
    """
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"

    headers = {"User-Agent": _USER_AGENT}
    if etag:
        headers["If-None-Match"] = etag

    timeout = aiohttp.ClientTimeout(total=15)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as response:
                new_etag = response.headers.get("ETag", "")
                last_modified = response.headers.get("Last-Modified", "")

                # 304 Not Modified — нет новых видео
                if response.status == 304:
                    return [], new_etag or etag, last_modified

                if response.status != 200:
                    return [], etag, last_modified

                content = await response.text()
                root = ET.fromstring(content)

                ns = {"atom": "http://www.w3.org/2005/Atom"}
                entries = root.findall("atom:entry", ns)

                videos = []
                for entry in entries:
                    video = _parse_rss_entry(entry)
                    if video and video.get("video_id"):
                        videos.append(video)

                return videos, new_etag or etag, last_modified

    except asyncio.TimeoutError:
        logger.debug("YouTube/RSS: таймаут канала %s", channel_id)
        return [], etag, ""
    except ET.ParseError as e:
        logger.debug("YouTube/RSS: ошибка парсинга XML канала %s: %s", channel_id, e)
        return [], etag, ""
    except Exception as e:
        logger.debug("YouTube/RSS: ошибка канала %s: %s", channel_id, e)
        return [], etag, ""


async def _fetch_all_channels_rss(state: dict) -> list[dict]:
    """
    Параллельно загружает RSS всех каналов.
    Возвращает список новых видео.
    """
    channel_etags = state.get("channel_etags", {})
    all_videos = []

    tasks = []
    for ch in _YOUTUBE_CHANNELS:
        ch_id = ch.get("id", "")
        if not ch_id:
            continue
        etag = channel_etags.get(ch_id, "")
        tasks.append(_fetch_channel_rss(ch_id, etag))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.debug("YouTube/RSS: ошибка канала #%d: %s", i, result)
            continue

        videos, new_etag, last_modified = result
        ch = _YOUTUBE_CHANNELS[i] if i < len(_YOUTUBE_CHANNELS) else {}
        ch_id = ch.get("id", "")

        # Обновляем etag в состоянии
        if new_etag:
            channel_etags[ch_id] = new_etag

        if videos:
            # Добавляем channel_id
            for v in videos:
                v["channel_id"] = ch_id
            logger.debug(
                "YouTube/RSS: '%s' → %d видео (etag: %s)",
                ch.get("name", ch_id), len(videos), bool(new_etag),
            )
            all_videos.extend(videos)

    state["channel_etags"] = channel_etags
    return all_videos


# ═════════════════════════════════════════════════════════════════════════════
#  Стратегия 2: Поиск через YouTube RSS (search RSS)
# ═════════════════════════════════════════════════════════════════════════════

async def _fetch_search_rss(query: str, max_results: int = 10) -> list[dict]:
    """
    Использует YouTube search RSS для быстрого поиска без API ключа.
    """
    # YouTube search RSS (unofficial but works)
    params = urllib.parse.urlencode({"q": query})
    url = f"https://www.youtube.com/feeds/videos.xml?search_query={params}"

    headers = {"User-Agent": _USER_AGENT}
    timeout = aiohttp.ClientTimeout(total=15)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as response:
                if response.status != 200:
                    return []

                content = await response.text()
                root = ET.fromstring(content)

                ns = {"atom": "http://www.w3.org/2005/Atom"}
                entries = root.findall("atom:entry", ns)

                videos = []
                for entry in entries[:max_results]:
                    video = _parse_rss_entry(entry)
                    if video and video.get("video_id"):
                        videos.append(video)

                return videos

    except Exception as e:
        logger.debug("YouTube/SearchRSS: ошибка для '%s': %s", query, e)
        return []


# ═════════════════════════════════════════════════════════════════════════════
#  Стратегия 3: Invidious API (с фильтром даты)
# ═════════════════════════════════════════════════════════════════════════════

async def _fetch_dynamic_instances() -> list[str]:
    """Загружает список доступных Invidious инстансов (кэш 6ч)."""
    global _dynamic_instances, _dynamic_instances_timestamp

    now = time.time()
    if _dynamic_instances and (now - _dynamic_instances_timestamp) < _DYNAMIC_CACHE_TTL:
        return _dynamic_instances

    logger.debug("YouTube: загрузка динамических Invidious инстансов...")

    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                "https://api.invidious.io/instances.json"
            ) as response:
                if response.status != 200:
                    return _dynamic_instances

                data = await response.json()
                instances = []

                for entry in data:
                    if not isinstance(entry, list) or len(entry) < 2:
                        continue
                    info = entry[1]
                    if not isinstance(info, dict):
                        continue

                    uri = info.get("uri", "")
                    if not uri or not uri.startswith("https://"):
                        continue

                    api_ok = info.get("type", "") in (1, "1", "https")
                    stats = info.get("stats", {})
                    if isinstance(stats, dict):
                        status = stats.get("status", "")
                        if status and status != "ok":
                            continue

                    if api_ok:
                        instances.append(uri.rstrip("/"))

                if instances:
                    _dynamic_instances[:] = instances
                    _dynamic_instances_timestamp = now
                    logger.debug(
                        "YouTube: загружено %d динамических Invidious инстансов",
                        len(instances),
                    )

    except Exception as e:
        logger.debug("YouTube: ошибка загрузки Invidious инстансов: %s", e)

    return _dynamic_instances


async def _get_invidious_instances() -> list[str]:
    """Возвращает объединённый список инстансов."""
    dynamic = await _fetch_dynamic_instances()
    all_instances = list(dynamic)
    for inst in _STATIC_INVIDIOUS_INSTANCES:
        if inst not in all_instances:
            all_instances.append(inst)
    return all_instances


def _remove_bad_instance(instance_url: str) -> None:
    """Удаляет неработающий инстанс из кэша."""
    _dynamic_instances[:] = [
        inst for inst in _dynamic_instances if inst != instance_url
    ]


def _parse_invidious_item(item: dict) -> dict:
    """Преобразует элемент Invidious API в унифицированный формат."""
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


async def _search_invidious(
    query: str,
    sort_by: str = "relevance",
    date: str = "month",
    max_results: int = 10,
) -> list[dict]:
    """Ищет видео через Invidious API с фильтром даты."""
    instances = await _get_invidious_instances()
    timeout = aiohttp.ClientTimeout(total=10)

    for instance in instances[:5]:  # Максимум 5 инстансов (быстрее)
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
                            "YouTube/Invidious: '%s' → %d через %s",
                            query, len(results), instance,
                        )
                        return results

        except asyncio.TimeoutError:
            _remove_bad_instance(instance)
        except Exception as e:
            logger.debug("YouTube/Invidious: %s ошибка: %s", instance, e)
            _remove_bad_instance(instance)

    return []


# ═════════════════════════════════════════════════════════════════════════════
#  Стратегия 4: yt-dlp (фоллбэк)
# ═════════════════════════════════════════════════════════════════════════════

def _search_ytdlp_sync(
    query: str,
    max_results: int = 10,
) -> list[dict]:
    """Ищет видео через yt-dlp (синхронная для executor)."""
    try:
        import yt_dlp
    except ImportError:
        return []

    import logging as _stdlib_logging
    _stdlib_logging.getLogger("yt-dlp").setLevel(_stdlib_logging.CRITICAL)
    _stdlib_logging.getLogger("yt_dlp").setLevel(_stdlib_logging.CRITICAL)

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
        logger.warning("YouTube/yt-dlp: ошибка '%s': %s", query, e)

    return results


async def _search_ytdlp(query: str, max_results: int = 10) -> list[dict]:
    """Ищет видео через yt-dlp (асинхронная обёртка)."""
    import logging as _stdlib_logging
    try:
        import yt_dlp
        _stdlib_logging.getLogger("yt-dlp").setLevel(_stdlib_logging.CRITICAL)
        _stdlib_logging.getLogger("yt_dlp").setLevel(_stdlib_logging.CRITICAL)
    except ImportError:
        return []

    loop = asyncio.get_running_loop()
    try:
        results = await loop.run_in_executor(
            _thread_pool, _search_ytdlp_sync, query, max_results
        )
    except Exception as e:
        logger.warning("YouTube/yt-dlp: executor ошибка: %s", e)
        results = []

    return results


# ═════════════════════════════════════════════════════════════════════════════
#  Объединённый поиск
# ═════════════════════════════════════════════════════════════════════════════

async def _search_videos(
    query: str,
    sort_by: str = "relevance",
    date_filter: str = "month",
    max_results: int = 10,
) -> list[dict]:
    """
    Ищет видео через бэкенды по очереди: Invidious → yt-dlp.
    yt-dlp не умеет фильтр по дате — пост-фильтрация по timestamp.
    """
    # Backend 1: Invidious (с фильтром даты)
    results = await _search_invidious(
        query=query, sort_by=sort_by, date=date_filter, max_results=max_results,
    )
    if results:
        return results

    # Backend 2: yt-dlp (без фильтра, post-filter)
    results = await _search_ytdlp(query=query, max_results=max_results)
    return results


async def _search_all_queries_parallel(
    lookback_days: int = 90,
    max_results_per_query: int = 10,
) -> list[dict]:
    """
    Параллельно ищет по всем поисковым запросам через asyncio.gather.
    Это значительно ускоряет поиск — все запросы идут одновременно.
    """
    # Определяем фильтр даты для Invidious
    if lookback_days <= 7:
        date_filter = "week"
    elif lookback_days <= 30:
        date_filter = "month"
    else:
        date_filter = ""  # Invidious не умеет > month — используем все

    tasks = []
    for query, sort_by in _SEARCH_QUERIES:
        tasks.append(_search_videos(
            query=query,
            sort_by=sort_by,
            date_filter=date_filter,
            max_results=max_results_per_query,
        ))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_videos = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.debug("YouTube: ошибка запроса #%d: %s", i, result)
            continue
        if result:
            all_videos.extend(result)

    return all_videos


# ═════════════════════════════════════════════════════════════════════════════
#  Фильтрация контента
# ═════════════════════════════════════════════════════════════════════════════

def _filter_video(
    video: dict,
    min_views: int = 0,
    min_likes: int = 0,
    lookback_days: int = 90,
    require_dayz_keyword: bool = True,
) -> str | None:
    """
    Фильтрует видео. Возвращает None если проходит все фильтры,
    либо строку с причиной отбраковки для статистики ворнки.

    Причины:
      'live'       — прямой эфир
      'long'       — длительность > 5 минут
      'garbage'    — мусорный стрим
      'old'        — старше lookback_days
      'irrelevant' — не релевантно DayZ
      'views'      — мало просмотров/лайков
    """
    # Прямые эфиры — нет
    if video.get("is_live", False):
        return "live"

    # Длительность
    duration = video.get("duration", 0) or 0
    if duration > _LONG_VIDEO_MAX:
        return "long"

    # Стримы и трансляции — полностью отсеиваем
    title = video.get("title", "")
    if _is_stream_garbage(title):
        return "live"

    # Фильтр даты (только если есть published timestamp)
    published = video.get("published", 0) or 0
    if published > 0 and not _is_within_lookback(published, lookback_days):
        return "old"

    # Релевантность DayZ
    description = video.get("description", "")
    if require_dayz_keyword and not _is_dayz_related(title, description):
        return "irrelevant"

    # Просмотры/лайки (только когда статистика доступна)
    views = video.get("views", 0) or 0
    likes = video.get("likes", 0) or 0

    if views > 0:
        if min_views > 0 and views < min_views:
            return "views"
        if min_likes > 0 and likes < min_likes:
            return "views"
    # Если views=0 (RSS без статистики или yt-dlp flat) — пропускаем

    return None  # Проходит все фильтры


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
    """Скачивает видео через yt-dlp."""
    import logging as _stdlib_logging
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
    """Скачивает короткое видео с YouTube с поддержкой cookies."""
    url = video.get("url", "")
    video_id = video.get("video_id", "unknown")
    if not url:
        return None

    os.makedirs(downloads_dir, exist_ok=True)
    output_template = os.path.join(downloads_dir, "%(id)s.%(ext)s")
    max_filesize = max_filesize_mb * 1024 * 1024

    # Попытка 1: cookies.txt
    script_dir = os.path.dirname(os.path.abspath(__file__))
    cookies_path = os.path.join(script_dir, "cookies.txt")

    if os.path.isfile(cookies_path):
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            _thread_pool, _download_ytdlp_sync,
            url, output_template, cookies_path, "", max_filesize,
        )
        if result and os.path.isfile(result):
            logger.info("YouTube/download: скачано через cookies.txt → %s", result)
            return result

    # Попытка 2: браузер cookies
    import sys
    platform = sys.platform.lower()
    browsers = ["chrome", "firefox", "brave"] if not platform.startswith("win") else ["chrome", "edge", "brave", "firefox"]

    for browser in browsers:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            _thread_pool, _download_ytdlp_sync,
            url, output_template, "", browser, max_filesize,
        )
        if result and os.path.isfile(result):
            logger.info("YouTube/download: скачано через %s → %s", browser, result)
            return result

    # Попытка 3: без cookies
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        _thread_pool, _download_ytdlp_sync,
        url, output_template, "", "", max_filesize,
    )
    if result and os.path.isfile(result):
        logger.info("YouTube/download: скачано без cookies → %s", result)
        return result

    logger.warning("YouTube/download: не удалось скачать '%s'", url)
    return None


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
    Проверяет YouTube на наличие новых DayZ видео.

    Стратегии (параллельно):
      1. RSS-ленты каналов — свежие видео напрямую
      2. Поисковые запросы через Invidious/yt-dlp

    Фильтры:
      - lookback_days (default 90 = 3 месяца)
      - min_views / min_likes
      - Релевантность DayZ
      - Длительность ≤ 5 мин
    """
    if config is None:
        config = {}

    min_views = int(config.get("youtube_min_views", 0))
    min_likes = int(config.get("youtube_min_likes", 0))
    max_per_check = int(config.get("youtube_max_per_check", 10))
    max_results = int(config.get("youtube_max_results", 10))
    lookback_days = int(config.get("youtube_lookback_days", _DEFAULT_LOOKBACK_DAYS))

    state = _load_state()
    posted_ids = state.get("posted_ids", {})
    if not isinstance(posted_ids, dict):
        posted_ids = {}

    all_new_videos = []
    seen_video_ids = set()
    processed_count = 0

    # ─── Автоочистка posted_ids от старых записей ────────────────────────
    # Удаляем записи старше lookback_days, чтобы не накапливать бесконечно
    now_ts = time.time()
    cutoff_ts = now_ts - (lookback_days * 86400)
    stale_count = 0
    for vid, info in list(posted_ids.items()):
        entry_ts = info.get("timestamp", 0) or 0
        if entry_ts > 0 and entry_ts < cutoff_ts:
            del posted_ids[vid]
            stale_count += 1
    if stale_count:
        logger.info("YouTube: очищено %d старых записей из posted_ids", stale_count)

    # ─── Стратегия 1: RSS каналов (параллельно) ─────────────────────────
    rss_start = time.time()

    try:
        rss_videos = await _fetch_all_channels_rss(state)
    except Exception as e:
        logger.error("YouTube: RSS ошибка: %s", e)
        rss_videos = []

    # ─── Стратегия 2: Поисковые запросы (параллельно через gather) ────
    search_start = time.time()

    try:
        search_videos = await _search_all_queries_parallel(
            lookback_days=lookback_days,
            max_results_per_query=max_results,
        )
    except Exception as e:
        logger.error("YouTube: поиск ошибка: %s", e)
        search_videos = []

    # ─── Объединяем и фильтруем с воронкой ────────────────────────────────
    combined_videos = []
    for v in rss_videos:
        v["_priority_source"] = "rss"
        combined_videos.append(v)
    for v in search_videos:
        v["_priority_source"] = "search"
        combined_videos.append(v)

    # Счётчики ворнки фильтрации
    funnel = {
        "total": len(combined_videos),
        "dup": 0,        # Дубликаты (seen_video_ids)
        "already": 0,    # Уже было в posted_ids
        "live": 0,       # Стримы/трансляции (любые упоминания stream/стрим/live)
        "long": 0,       # Длительность > 10 мин
        "old": 0,        # Старше lookback_days
        "irrelevant": 0, # Не релевантно DayZ
        "views": 0,      # Мало просмотров/лайков
    }

    for video in combined_videos:
        if processed_count >= max_per_check:
            break

        video_id = video.get("video_id", "")
        if not video_id:
            continue

        # Дедупликация
        if video_id in seen_video_ids:
            funnel["dup"] += 1
            continue
        seen_video_ids.add(video_id)

        if video_id in posted_ids:
            funnel["already"] += 1
            continue

        # Фильтрация (теперь возвращает причину)
        reject_reason = _filter_video(
            video,
            min_views=min_views,
            min_likes=min_likes,
            lookback_days=lookback_days,
        )
        if reject_reason:
            funnel[reject_reason] = funnel.get(reject_reason, 0) + 1
            continue

        # Категория
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
            "source": video.get("source", "unknown"),
        }

    # Сохраняем состояние
    state["posted_ids"] = posted_ids
    state["last_check"] = time.time()
    _save_state(state)

    # ─── Логируем воронку одной строкой ──────────────────────────────────
    elapsed = time.time() - rss_start
    n = funnel["total"]
    dups = funnel["dup"]
    already = funnel["already"]
    live = funnel["live"]
    long = funnel["long"]
    old = funnel["old"]
    irrelevant = funnel["irrelevant"]
    views_r = funnel["views"]
    new_count = len(all_new_videos)

    parts = [f"найдено: {n}"]
    if dups:
        parts.append(f"дубли: {dups}")
    if already:
        parts.append(f"уже было: {already}")
    if live:
        parts.append(f"стримы: {live}")
    if long:
        parts.append(f"длинные(>10мин): {long}")
    if old:
        parts.append(f"старые(>{lookback_days}д): {old}")
    if irrelevant:
        parts.append(f"не-DayZ: {irrelevant}")
    if views_r:
        parts.append(f"мало views: {views_r}")
    parts.append(f"новых: {new_count}")
    parts.append(f"({elapsed:.1f}с)")

    logger.info("YouTube: %s", " → ".join(parts))

    # Логируем каждое новое видео
    for v in all_new_videos:
        logger.info(
            "YouTube [+]: %s (%s, %s, %s views)",
            v.get("title", "")[:60],
            _format_duration(v.get("duration", 0)),
            v.get("category", "?"),
            _format_views(v.get("views", 0)),
        )

    # ─── Сохраняем в БД и отправляем в веб-панель ────────────────────────
    if db and all_new_videos:
        await _save_videos_to_db(
            db=db,
            videos=all_new_videos,
            config=config,
            web_panel_url=web_panel_url,
            web_panel_api_key=web_panel_api_key,
        )

    return all_new_videos


async def _save_videos_to_db(
    db,
    videos: list[dict],
    config: dict,
    web_panel_url: str = "",
    web_panel_api_key: str = "",
) -> None:
    """Сохраняет видео в БД и отправляет на веб-панель."""
    downloads_dir = config.get("images_dir", "downloads")
    do_download = config.get("youtube_download", True)

    for video in videos:
        video_id = video.get("video_id", "")
        ch_title = video.get("channel_title", "YouTube")
        title = video.get("title", "Без названия")
        description = video.get("description", "")
        url = video.get("url", "")
        category = video.get("category", "other")

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
            logger.debug("YouTube: дубликат/ошибка: %s (%s)", video_id, title[:50])
            continue

        # AI-пересказ видео + полноценный Telegram-пост
        priority = "low"
        ai_summary = f"[{category}] {title}"
        ai_post = msg if isinstance(msg, str) else str(msg)

        if category in ("updates", "events", "weapons", "secrets"):
            priority = "medium"

        try:
            from ai_analyzer import _get_analyzer
            analyzer = _get_analyzer()
            ai_result = await analyzer.analyze_youtube_video(video)
            if ai_result:
                priority = ai_result.get("priority", priority)
                ai_summary = ai_result.get("summary", ai_summary) or ai_summary
                ai_post = ai_result.get("formatted_post", ai_post) or ai_post
                # Обновляем категорию из AI-анализа если differs
                ai_type = ai_result.get("news_type", "")
                if ai_type and ai_type != "other":
                    category = ai_type
                logger.info("YouTube AI: '%s' → %s (%s)",
                            title[:40], ai_type, priority)
        except Exception as e:
            logger.debug("YouTube: AI недоступен: %s", e)

        # Сохраняем обработку
        await db.save_processed(
            message_id=msg_id,
            news_type=category,
            priority=priority,
            should_publish=False,
            summary=ai_summary or "",
            server_name=ch_title,
            formatted_post=ai_post if isinstance(ai_post, str) else str(ai_post),
        )

        # Веб-панель
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
                        "formattedPost": ai_post if isinstance(ai_post, str) else str(ai_post),
                    },
                    web_app_url=web_panel_url,
                    bot_api_key=web_panel_api_key or None,
                )
            except Exception as e:
                logger.debug("YouTube: ошибка панели: %s", e)

        # Скачивание shorts
        if do_download and video.get("duration", 0) <= _SHORTS_MAX_DURATION:
            try:
                filepath = await download_short(video, downloads_dir=downloads_dir)
                if filepath:
                    logger.info(
                        "YouTube: скачано → %s (%.1f MB)",
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
    ai_analyzer=None,
    ai_analyze: bool = True,
    min_views: int = 0,
    min_likes: int = 0,
    check_interval_hours: int = 2,
    max_per_check: int = 10,
    download_shorts: bool = True,
    shutdown_event=None,
    notify_callback=None,
    web_panel_url: str = "",
    web_panel_api_key: str = "",
    notification_callback=None,
    lookback_days: int = 90,
) -> None:
    """
    Запускает постоянный мониторинг YouTube.

    Профессиональная система с 4 стратегиями поиска, параллельным выполнением
    и пост-фильтрацией по дате.

    Args:
        db: Экземпляр Database.
        ai_analyzer: AI анализатор.
        ai_analyze: Включить AI анализ.
        min_views: Минимум просмотров.
        min_likes: Минимум лайков.
        check_interval_hours: Интервал проверки (часы).
        max_per_check: Максимум видео за проверку.
        download_shorts: Скачивать шортсы.
        shutdown_event: asyncio.Event для остановки.
        notify_callback: Callback уведомлений.
        web_panel_url: URL веб-панели.
        web_panel_api_key: API ключ панели.
        notification_callback: Алиас notify_callback.
        lookback_days: За сколько дней искать (default 90 = ~3 месяца).
    """
    _notify = notify_callback or notification_callback

    if check_interval_hours < 1:
        check_interval_hours = 1

    config = {
        "youtube_min_views": min_views,
        "youtube_min_likes": min_likes,
        "youtube_max_per_check": max_per_check,
        "youtube_download": download_shorts,
        "ai_analyze": ai_analyze,
        "images_dir": "downloads",
        "youtube_lookback_days": lookback_days,
    }

    logger.info(
        "YouTube монитор: запущен "
        "(интервал=%dч, views≥%d, likes≥%d, max=%d, lookback=%dд, download=%s)",
        check_interval_hours, min_views, min_likes, max_per_check,
        lookback_days, download_shorts,
    )

    while True:
        if shutdown_event and shutdown_event.is_set():
            logger.info("YouTube монитор: остановлен")
            break

        try:
            start_time = time.time()

            new_videos = await check_for_new_videos(
                db=db,
                config=config,
                web_panel_url=web_panel_url,
                web_panel_api_key=web_panel_api_key,
            )

            elapsed = time.time() - start_time

            # Уведомления
            if new_videos and _notify:
                for video in new_videos:
                    try:
                        await _notify(video)
                    except Exception as e:
                        logger.debug("YouTube: ошибка уведомления: %s", e)

            # Очистка
            cleanup_old_downloads(downloads_dir="downloads")

        except Exception as e:
            logger.error("YouTube монитор: критическая ошибка: %s", e, exc_info=True)

        # Ожидание до следующей проверки
        wait_seconds = check_interval_hours * 3600
        while wait_seconds > 0:
            if shutdown_event and shutdown_event.is_set():
                logger.info("YouTube монитор: остановлен")
                return
            sleep_chunk = min(30, wait_seconds)
            await asyncio.sleep(sleep_chunk)
            wait_seconds -= sleep_chunk


# ═════════════════════════════════════════════════════════════════════════════
#  Standalone запуск
# ═════════════════════════════════════════════════════════════════════════════

async def main():
    """Standalone запуск для тестирования."""
    import json as _json

    config_path = os.environ.get("CONFIG_PATH", "config.json")
    config = {}
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = _json.load(f)
    except FileNotFoundError:
        logger.warning("config.json не найден")

    logger.info("YouTube монитор: standalone режим (lookback: %d дней)", config.get("youtube_lookback_days", 90))

    videos = await check_for_new_videos(db=None, config=config)

    if videos:
        logger.info("YouTube: найдено %d видео", len(videos))
        for v in videos:
            print(format_video_message(v, v.get("category", "")))
            print("─" * 60)
    else:
        logger.info("YouTube: новых видео не найдено")


if __name__ == "__main__":
    asyncio.run(main())
