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
import json
import os
import re
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

import aiohttp

from logger import logger

# ─── Константы ─────────────────────────────────────────────────────────────

# Пороги длительности (секунды)
_SHORTS_MAX_DURATION = 90    # Порог для "шортс" (YouTube Shorts)
_LONG_VIDEO_MAX = 1200        # > 20 минут — не берём (по умолчанию; можно переопределить через config)

# Пороги даты
_DEFAULT_LOOKBACK_DAYS = 90   # По умолчанию ищем за 3 месяца

# Минимум кириллических символов для определения русского текста
_MIN_RU_CHARS = 5  # Строгий порог — отсекает видео с 1-2 кириллическими символами

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

# FIX: единая HTTP-сессия для всех запросов
_http_session: aiohttp.ClientSession | None = None

async def _get_session() -> aiohttp.ClientSession:
    """Возвращает единую aiohttp сессию (shared)."""
    global _http_session
    if _http_session is None or _http_session.closed:
        timeout = aiohttp.ClientTimeout(total=15)
        connector = aiohttp.TCPConnector(limit=20)
        _http_session = aiohttp.ClientSession(
            timeout=timeout,
            connector=connector,
            headers={"User-Agent": _USER_AGENT},
        )
    return _http_session

# FIX: семафор ограничивает параллельные yt-dlp
_ytdlp_semaphore: asyncio.Semaphore | None = None  # FIX-2: ленивая инициализация (Python 3.12+)

async def _get_ytdlp_semaphore() -> asyncio.Semaphore:
    """Ленивая инициализация семафора внутри event loop."""
    global _ytdlp_semaphore
    if _ytdlp_semaphore is None:
        _ytdlp_semaphore = asyncio.Semaphore(4)
    return _ytdlp_semaphore

# ─── Каналы DayZ для RSS мониторинга ─────────────────────────────────────────
# ID каналов YouTube — источники самого свежего контента.
# Каналы загружаются из config.json (youtube_channels),
# но если там пусто — используются каналы по умолчанию ниже.
# Можно добавлять/удалять каналы через GUI.
_DEFAULT_YOUTUBE_CHANNELS = [
    # Только русскоязычные DayZ каналы
    {"id": "UCdFrJ3cFV0sBcSkGyOz8o7Q", "name": "DayZ Россия"},
    {"id": "UCnXzJG3RgDwRqbYQMq9LlgA", "name": "GIGA DayZ"},
]

# Блок-лист каналов — англоязычные/мусорные, никогда не парсятся
_CHANNEL_BLOCKLIST = {
    "UCvQPcPcEzzMPTjTMzGCRN0g",  # DayZ Official (английский)
    "UCxMACMoQE1AJTKmjmCCdTsA",  # Bohemia Interactive (английский)
    "UCaOQfLYzm2Y8kGxNFbQkFRA",  # DayZ Twitch (в основном стримы/английский)
}

# Текущий рабочий список каналов (загружается из config или дефолтный)
_YOUTUBE_CHANNELS: list[dict] = []

async def _resolve_handle_to_id(handle: str) -> str:
    """Конвертирует @handle в UC... Channel ID через парсинг HTML."""
    handle = handle.strip().lstrip("@")
    if not handle:
        return ""
    url = f"https://www.youtube.com/@{handle}"
    try:
        session = await _get_session()
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                return ""
            html = await resp.text()
        m = __import__("re").search(r'"channelId":"(UC[\w-]{22})"', html)
        if m:
            logger.info("YouTube: @%s → %s", handle, m.group(1))
            return m.group(1)
    except Exception as e:
        logger.debug("YouTube: не удалось резолвить @%s: %s", handle, e)
    return ""


def load_youtube_channels(config: dict | None = None) -> list[dict]:
    """Загружает список каналов из config.json или возвращает дефолтный."""
    global _YOUTUBE_CHANNELS
    if config is None:
        config = {}
    channels = config.get("youtube_channels", [])
    if isinstance(channels, list) and channels:
        valid = []
        for ch in channels:
            if isinstance(ch, dict) and ch.get("id"):
                valid.append(ch)
            elif isinstance(ch, str) and ch.strip():
                valid.append({"id": ch.strip(), "name": ""})
        if valid:
            _YOUTUBE_CHANNELS = valid
            logger.info("YouTube: загружено %d каналов из config.json", len(valid))
            return valid
    # Fallback на дефолтные
    _YOUTUBE_CHANNELS = list(_DEFAULT_YOUTUBE_CHANNELS)
    return _YOUTUBE_CHANNELS

# ─── Поисковые запросы для API поиска ────────────────────────────────────────
# Только русскоязычные запросы для поиска шортсов
_SEARCH_QUERIES = [
    # Только запросы для поиска YouTube Shorts (вертикальные <=90с)
    ("DayZ shorts", "date"),
    ("DayZ шортс", "date"),
    ("DayZ рилс", "date"),
    ("DayZ приколы шортс", "relevance"),
    ("DayZ мем шортс", "relevance"),
    ("DayZ пвп шортс", "date"),
    ("DayZ баг шортс", "relevance"),
    ("DayZ гайд шортс", "date"),
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
# FIX: объединены два regex в один для скорости
_STREAM_FILTER = re.compile(
    r"(?i)"
    r"\bstream\b|\bstreams?\b|\bстрим\b|\bстримы\b|\blive\b|\bлайв\b|\bтрансляци\b|\bbroadcast\b|"
    r"стрим\s*№\s*\d|стрим\s*#\s*\d|stream\s*#?\s*\d|live\s*#?\s*\d|"
    r"пост-вайп|post.?wipe|PVE\s*проект|PVP\s*проект|"
    r"►►|▶▶|"
    r"donationalerts|donate\s*alert|поддержи\s*стрим|"
    r"click\s*here\s*to\s*subscribe|ссылка\s*на\s*донат|"
    r"делай\s*ставку|bet\s*now|промокод|скидка\s*\d+%|играй\s*бесплатно",
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
    return bool(_STREAM_FILTER.search(title))


def _is_within_lookback(published_ts: int | float, lookback_days: int) -> bool:
    """
    Проверяет, находится ли видео в диапазоне lookback_days от текущей даты.
    published_ts — Unix timestamp в секундах.
    """
    if not published_ts or published_ts <= 0:
        return True  # нет даты — не фильтруем

    # FIX-4: защита от миллисекунд (повторная на случай других источников)
    if published_ts > 9_999_999_999:
        published_ts = published_ts // 1000

    # FIX-4: защита от дат из будущего
    now = time.time()
    if published_ts > now + 86400:
        logger.debug(
            "YouTube: дата из будущего ts=%s, пропускаем фильтр", published_ts
        )
        return True

    # FIX-4: защита от дат до выхода DayZ (декабрь 2013)
    DAYZ_RELEASE_TS = 1386806400  # 2013-12-16 UTC
    if published_ts < DAYZ_RELEASE_TS:
        logger.debug(
            "YouTube: дата до выхода DayZ ts=%s, видео невалидно", published_ts
        )
        return False

    cutoff = now - (lookback_days * 86400)
    return published_ts >= cutoff


def _parse_iso8601_date(date_str: str) -> float:  # FIX: ISO 8601 вместо RFC 2822 (YouTube RSS отдаёт ISO)
    """Парсит ISO 8601 дату в Unix timestamp."""
    if not date_str:
        return 0
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
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


def _save_state(state: dict) -> None:
    """Сохраняет состояние в JSON-файл. При ошибке прав — пробует /tmp."""
    for target in [_STATE_FILE, f"/tmp/{_STATE_FILE}"]:
        try:
            with open(target, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
            return
        except OSError:
            continue
    logger.warning("YouTube: не удалось сохранить состояние")


def _load_state() -> dict:
    """Загружает состояние из JSON-файла с fallback на /tmp."""
    for target in [_STATE_FILE, f"/tmp/{_STATE_FILE}"]:
        try:
            if os.path.exists(target):
                with open(target, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if "posted_ids" not in data:
                    data["posted_ids"] = {}
                if "channel_etags" not in data:
                    data["channel_etags"] = {}
                return data
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("YouTube: не удалось загрузить состояние из %s: %s", target, e)
            continue
    return {"posted_ids": {}, "last_check": 0, "channel_etags": {}}


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
        published = _parse_iso8601_date(published_el.text)

    # Updated date (fallback)
    updated = 0
    updated_el = entry.find("atom:updated", ns)
    if updated_el is not None and updated_el.text:
        updated = _parse_iso8601_date(updated_el.text)

    # Duration (из yt:duration или media:group/media:content)
    duration = 0
    views = 0       # FIX: инициализация до if group
    likes = 0       # FIX: инициализация до if group
    thumbnail = ""  # FIX: инициализация до if group
    description = "" # FIX: инициализация до if group
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
    if group is not None:
        desc_el = group.find("media:description", ns)
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
        session = await _get_session()
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

    # Резолвим @handle → UC... перед RSS
    for ch in _YOUTUBE_CHANNELS:
        ch_id = ch.get("id", "")
        if ch_id.startswith("@"):
            resolved = await _resolve_handle_to_id(ch_id)
            if resolved:
                ch["id"] = resolved
                ch["_was_handle"] = ch_id
                logger.info("YouTube/RSS: @%s резолвен в %s", ch_id, resolved)

    tasks = []
    rss_channel_indices = []
    for i, ch in enumerate(_YOUTUBE_CHANNELS):
        ch_id = ch.get("id", "")
        if not ch_id:
            continue
        if ch_id.startswith("@"):
            logger.debug("YouTube/RSS: не удалось резолвить @handle '%s'", ch_id)
            continue
        etag = channel_etags.get(ch_id, "")
        tasks.append(_fetch_channel_rss(ch_id, etag))
        rss_channel_indices.append(i)

    results = await asyncio.gather(*tasks, return_exceptions=True)

    for j, result in enumerate(results):
        if isinstance(result, Exception):
            logger.debug("YouTube/RSS: ошибка канала #%d: %s", j, result)
            continue

        videos, new_etag, last_modified = result
        orig_i = rss_channel_indices[j] if j < len(rss_channel_indices) else j
        ch = _YOUTUBE_CHANNELS[orig_i] if orig_i < len(_YOUTUBE_CHANNELS) else {}
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
#  Стратегия 2: Invidious API (с фильтром даты)
# ═════════════════════════════════════════════════════════════════════════════

async def _fetch_dynamic_instances() -> list[str]:
    """Загружает список доступных Invidious инстансов (кэш 6ч)."""
    global _dynamic_instances, _dynamic_instances_timestamp

    now = time.time()
    if _dynamic_instances and (now - _dynamic_instances_timestamp) < _DYNAMIC_CACHE_TTL:
        return _dynamic_instances

    logger.debug("YouTube: загрузка динамических Invidious инстансов...")

    try:
        session = await _get_session()
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

    # FIX-1: миллисекунды → секунды
    published_raw = item.get("published", 0) or 0
    if published_raw > 9_999_999_999:
        published_raw = published_raw // 1000

    return {
        "video_id": item.get("videoId", ""),
        "title": (item.get("title") or "").strip(),
        "channel_title": (item.get("author") or "").strip(),
        "channel_id": item.get("authorId", ""),
        "duration": duration,
        "views": views,
        "likes": likes,
        "published": published_raw,
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

    for instance in instances[:5]:  # Максимум 5 инстансов (быстрее)
        try:
            params = {
                "q": query,
                "sort_by": sort_by,
                "type": "video",
                "date": date,
                "page": 1,
            }

            session = await _get_session()
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
        "extractor_args": {"youtube": {"skip": ["dash", "hls"]}},  # FIX-3: ускоряем yt-dlp
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
            # FIX-3: fallback для duration из duration_string если extract_flat не отдал
            if not duration and entry.get("duration_string"):
                parts = entry["duration_string"].split(":")
                try:
                    if len(parts) == 2:
                        duration = int(parts[0]) * 60 + int(parts[1])
                    elif len(parts) == 3:
                        duration = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                except (ValueError, IndexError):
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
                # FIX-2: миллисекунды → секунды
                ts_raw = entry.get("timestamp", 0) or 0
                if ts_raw > 9_999_999_999:
                    ts_raw = ts_raw // 1000

                results.append({
                    "video_id": video_id,
                    "title": title,
                    "channel_title": uploader,
                    "channel_id": entry.get("channel_id", ""),
                    "duration": int(duration),
                    "views": int(view_count),
                    "likes": int(like_count),
                    "published": ts_raw,
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
        sem = await _get_ytdlp_semaphore()  # FIX-2: ленивая инициализация
        async with sem:
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
    # Invidious поддерживает: hour, today, week, month, year, all
    # Используем "year" для любого lookback > 30 дней — Invidious сам отфильтрует
    if lookback_days <= 7:
        date_filter = "week"
    elif lookback_days <= 30:
        date_filter = "month"
    else:
        date_filter = "year"

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
    max_duration: int = 0,
    require_dayz_keyword: bool = True,
    require_russian: bool = True,
    shorts_only: bool = True,
) -> str | None:
    """
    Фильтрует видео. Возвращает None если проходит все фильтры,
    либо строку с причиной отбраковки для статистики ворнки.

    Причины:
      'live'       — прямой эфир
      'long'       — длительность > max_duration (или _SHORTS_MAX_DURATION если shorts_only)
      'garbage'    — мусорный стрим
      'old'        — старше lookback_days
      'irrelevant' — не релевантно DayZ
      'views'      — мало просмотров/лайков
      'not_russian' — видео не на русском языке
      'not_shorts' — не является шортсом (вертикальным видео <=90с)
    """
    # Блок-лист каналов (английские/мусорные)
    ch_id = video.get("channel_id", "")
    if ch_id and ch_id in _CHANNEL_BLOCKLIST:
        return "blocked_channel"

    # Прямые эфиры — нет
    if video.get("is_live", False):
        return "live"

    # ─── Фильтр: только шортсы (вертикальные, <= 90 сек) ─────────
    duration = video.get("duration", 0) or 0
    if shorts_only and duration > _SHORTS_MAX_DURATION:
        return "not_shorts"

    # Длительность (max_duration=0 → используем _LONG_VIDEO_MAX)
    effective_max = max_duration if max_duration > 0 else _LONG_VIDEO_MAX
    if duration > effective_max:
        return "long"

    # Стримы и трансляции — полностью отсеиваем
    title = video.get("title", "")
    if _is_stream_garbage(title):
        return "live"

    # Фильтр даты (только если есть published timestamp)
    published = video.get("published", 0) or 0
    source = video.get("source", "")
    if published == 0:
        # FIX-5: yt-dlp flat часто не возвращает timestamp — не отсеиваем,
        # но логируем отдельно чтобы видеть масштаб проблемы
        if source not in ("rss", "yt_dlp"):
            return "no_date"
        # RSS с published=0 — пропускаем (дата может быть в updated)
    elif source != "invidious" and not _is_within_lookback(published, lookback_days):
        # FIX-3: debug-лог чтобы видеть реальные даты отсеянных видео
        try:
            readable = datetime.fromtimestamp(
                published, tz=timezone.utc
            ).strftime("%Y-%m-%d")
        except Exception:
            readable = str(published)
        logger.debug(
            "YouTube FILTER old: '%s' | published=%s | source=%s",
            video.get("title", "")[:50],
            readable,
            video.get("source", "unknown"),
        )
        return "old"

    # ─── Фильтр: только русскоязычные видео ───────────────────────
    if require_russian:
        title = video.get("title", "")
        description = video.get("description", "")
        channel_title = video.get("channel_title", "")
        # Проверяем русский текст в заголовке, описании ИЛИ названии канала
        combined_text = f"{title} {description} {channel_title}"
        if not _is_russian_text(combined_text):
            return "not_russian"

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
    max_filesize: int = 50 * 1024 * 1024,
) -> str | None:
    """Скачивает видео через yt-dlp. Только через cookies.txt — браузерный экспорт не работает."""
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
            "best[height<=720][ext=mp4]"
            "/best[ext=mp4]"
            "/bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/bestvideo[ext=mp4]+bestaudio[ext=m4a]"
            "/best"
        ),
        "outtmpl": output_template,
        "max_filesize": max_filesize,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "nocheckcertificate": True,
        "extractor_args": {"youtube": {"player_client": ["ios", "web"]}},
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
                "Mobile/15E148 Safari/604.1"
            ),
        },
    }

    if cookies_file and os.path.isfile(cookies_file):
        ydl_opts["cookiefile"] = cookies_file

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        if info:
            filepath = info.get("requested_downloads", [{}])
            if filepath:
                result_path = filepath[0].get("filepath") or None
                # Проверяем что файл не пустой
                if result_path and os.path.isfile(result_path):
                    if os.path.getsize(result_path) > 0:
                        return result_path
                    else:
                        os.remove(result_path)
                        logger.debug("YouTube/download: скачанный файл пустой, удалён")
                        return None
            video_id = info.get("id", "unknown")
            result_path = output_template.replace("%(id)s", video_id)
            if result_path and os.path.isfile(result_path) and os.path.getsize(result_path) > 0:
                return result_path
    except Exception as e:
        err_str = str(e)
        if "Sign in to confirm" in err_str or "bot" in err_str.lower():
            logger.warning("YouTube/download: YouTube требует cookies для '%s'. Положи cookies.txt рядом с ботом.", url)
        else:
            logger.debug("YouTube/download: yt-dlp ошибка: %s", e)

    return None


async def download_short(
    video: dict,
    downloads_dir: str = "downloads",
    max_filesize_mb: int = 50,
) -> str | None:
    """Скачивает короткое видео с YouTube. Требует cookies.txt для обхода блокировки."""
    url = video.get("url", "")
    if not url:
        return None

    os.makedirs(downloads_dir, exist_ok=True)
    output_template = os.path.join(downloads_dir, "%(id)s.%(ext)s")
    max_filesize = max_filesize_mb * 1024 * 1024

    # Ищем cookies.txt
    script_dir = os.path.dirname(os.path.abspath(__file__))
    cookies_path = os.path.join(script_dir, "cookies.txt")

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        _thread_pool, _download_ytdlp_sync,
        url, output_template, cookies_path, max_filesize,
    )
    if result:
        logger.info("YouTube/download: скачано → %s", result)
        return result

    logger.warning("YouTube/download: не удалось скачать '%s'%s", url,
                   ". Нужен cookies.txt — экспортируй из браузера расширением Get cookies.txt LOCALLY" if not os.path.isfile(cookies_path) else "")
    return None


# ═════════════════════════════════════════════════════════════════════════════
#  Основная логика мониторинга
# ═════════════════════════════════════════════════════════════════════════════

async def _fetch_channels_from_web_panel(
    web_panel_url: str,
    web_panel_api_key: str = "",
    timeout: float = 5.0,
) -> list[dict]:
    """Загружает список YouTube-каналов из веб-панели (API /api/youtube-channels)."""
    if not web_panel_url:
        return []
    try:
        import httpx
        headers = {"Content-Type": "application/json"}
        if web_panel_api_key:
            headers["Authorization"] = f"Bearer {web_panel_api_key}"
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                f"{web_panel_url}/api/youtube-channels",
                headers=headers,
            )
            if response.status_code == 200:
                data = response.json()
                channels = data.get("channels", [])
                if isinstance(channels, list) and channels:
                    logger.info("YouTube: загружено %d каналов из веб-панели", len(channels))
                    return channels
    except Exception as e:
        logger.debug("YouTube: не удалось загрузить каналы из веб-панели: %s", e)
    return []


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
      - Только русскоязычные видео (по умолчанию)
      - Только Shorts/вертикальные <=90с (по умолчанию)
      - lookback_days (default 90 = 3 месяца)
      - min_views / min_likes
      - Релевантность DayZ
    """
    if config is None:
        config = {}

    min_views = int(config.get("youtube_min_views", 0))  # FIX-6: verified defaults = 0
    min_likes = int(config.get("youtube_min_likes", 0))  # FIX-6: verified defaults = 0
    max_per_check = int(config.get("youtube_max_per_check", 10))
    max_results = int(config.get("youtube_max_results", 10))
    max_duration = int(config.get("youtube_max_duration", 0))
    lookback_days = int(config.get("youtube_lookback_days", _DEFAULT_LOOKBACK_DAYS))

    state = _load_state()
    posted_ids = state.get("posted_ids", {})
    if not isinstance(posted_ids, dict):
        posted_ids = {}

    all_new_videos = []
    seen_video_ids = set()
    processed_count = 0

    # ─── Загружаем каналы: config.json + веб-панель ─────────────────────
    channels = load_youtube_channels(config)

    # Попробуем дополнительно загрузить каналы из веб-панели
    web_channels = await _fetch_channels_from_web_panel(web_panel_url, web_panel_api_key)
    if web_channels:
        # Сливаем: берём уникальные каналы из веб-панели
        existing_ids = {ch.get("id", "") for ch in channels}
        for wc in web_channels:
            wc_id = wc.get("id", "") or wc.get("channel_id", "")
            if wc_id and wc_id not in existing_ids:
                channels.append({"id": wc_id, "name": wc.get("name", "")})
                existing_ids.add(wc_id)
        logger.info("YouTube: всего %d каналов (config + веб-панель)", len(channels))
    else:
        logger.info("YouTube: используется %d каналов для RSS", len(channels))

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

    # Настройки фильтрации из конфига
    require_russian = config.get("youtube_russian_only", True)
    shorts_only = config.get("youtube_shorts_only", True)

    # Счётчики ворнки фильтрации
    funnel = {
        "total": len(combined_videos),
        "dup": 0,
        "already": 0,
        "live": 0,
        "long": 0,
        "old": 0,
        "old_rss": 0,
        "old_invidious": 0,
        "old_ytdlp": 0,
        "irrelevant": 0,
        "views": 0,
        "no_date": 0,
        "not_russian": 0,
        "not_shorts": 0,
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
            max_duration=max_duration,
            require_russian=require_russian,
            shorts_only=shorts_only,
        )
        if reject_reason:
            funnel[reject_reason] = funnel.get(reject_reason, 0) + 1
            # FIX-5: детализация источника для "old"
            if reject_reason == "old":
                src = video.get("source", "unknown")
                key = f"old_{src}"
                funnel[key] = funnel.get(key, 0) + 1
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
    no_date = funnel["no_date"]
    not_russian = funnel.get("not_russian", 0)
    not_shorts = funnel.get("not_shorts", 0)
    new_count = len(all_new_videos)

    parts = [f"найдено: {n}"]
    if dups:
        parts.append(f"дубли: {dups}")
    if already:
        parts.append(f"уже было: {already}")
    if live:
        parts.append(f"стримы: {live}")
    if not_shorts:
        parts.append(f"не шортсы: {not_shorts}")
    if long:
        parts.append(f"длинные(>10мин): {long}")
    if old:
        parts.append(
            f"старые(>{lookback_days}д): {old} "
            f"[rss={funnel.get('old_rss',0)} "
            f"inv={funnel.get('old_invidious',0)} "
            f"ytdlp={funnel.get('old_ytdlp',0)}]"
        )
    if not_russian:
        parts.append(f"не русские: {not_russian}")
    if irrelevant:
        parts.append(f"не-DayZ: {irrelevant}")
    if views_r:
        parts.append(f"мало views: {views_r} [min_v={min_views} min_l={min_likes}]")
    if no_date:
        parts.append(f"без даты: {no_date}")
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
        except ImportError:  # FIX-4: отдельная обработка — модуль не найден
            logger.debug("YouTube: модуль ai_analyzer не найден, пропускаем AI-анализ")
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
            except ImportError:  # FIX-4: отдельная обработка — модуль не найден
                logger.debug("YouTube: модуль web_app_integration не найден, пропускаем")
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
    min_views: int = 0,  # FIX-6: verified defaults = 0
    min_likes: int = 0,  # FIX-6: verified defaults = 0
    check_interval_hours: int = 2,
    max_per_check: int = 10,
    max_duration: int = 0,
    download_shorts: bool = True,
    shutdown_event=None,
    notify_callback=None,
    web_panel_url: str = "",
    web_panel_api_key: str = "",
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
        notify_callback: async callable(video: dict) -> None
        web_panel_url: URL веб-панели.
        web_panel_api_key: API ключ панели.
        lookback_days: За сколько дней искать (default 90 = ~3 месяца).
    """
    _notify = notify_callback

    if check_interval_hours < 1:
        check_interval_hours = 1

    config = {
        "youtube_min_views": min_views,
        "youtube_min_likes": min_likes,
        "youtube_max_per_check": max_per_check,
        "youtube_max_duration": max_duration,
        "youtube_download": download_shorts,
        "ai_analyze": ai_analyze,
        "images_dir": "downloads",
        "youtube_lookback_days": lookback_days,
    }

    logger.info(
        "YouTube монитор: запущен "
        "(интервал=%dч, views≥%d, likes≥%d, max=%d, duration≤%dс, lookback=%dд, download=%s)",
        check_interval_hours, min_views, min_likes, max_per_check,
        max_duration if max_duration > 0 else _LONG_VIDEO_MAX,
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
                # FIX-7: закрываем сессию при остановке монитора
                if _http_session and not _http_session.closed:
                    await _http_session.close()
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

    # FIX-7: закрываем shared сессию при завершении
    global _http_session
    if _http_session and not _http_session.closed:
        await _http_session.close()
        logger.debug("YouTube: aiohttp сессия закрыта")


if __name__ == "__main__":
    asyncio.run(main())


# ═══════════════════════════════════════════════════════════════════════════════
# CHANGELOG
# FIX-1: ISO 8601 дата вместо RFC 2822 (YouTube RSS отдаёт ISO)
# FIX-2: ISO 8601 дата вместо RFC 2822
# FIX-3: реальные ID каналов (DayZ Official + Bohemia)
# FIX-4: удалён мёртвый Search RSS эндпоинт (не работает с 2023)
# FIX-5: удалён неиспользуемый search_start
# FIX-6: исправлен комментарий LONG_VIDEO_MAX
# FIX-7: воронка no_date
# FIX-8: shared aiohttp session
# FIX-9: семафор yt-dlp (макс 4)
# FIX-10: объединены stream-regex в один паттерн
# FIX-11: убран дубль notification_callback
# FIX-12: двойное присвоение ai_summary исправлено
#
# CHANGELOG v2
# FIX-2:  Semaphore ленивая инициализация (Python 3.12+)
# FIX-3:  duration fallback для yt-dlp flat extract + skip dash/hls
# FIX-4:  ImportError отдельно от Exception в заглушках
# FIX-5:  no_date не отсеивает yt_dlp без timestamp
# FIX-6:  удалены неиспользуемые импорты
# FIX-7:  закрытие aiohttp сессии при завершении
# FIX-8:  рабочие channel ID для немедленного теста
#
# CHANGELOG v3
# FIX-1: миллисекунды → секунды в _parse_invidious_item
# FIX-2: миллисекунды → секунды в _search_ytdlp_sync
# FIX-3: debug-лог реальных дат для отсеянных видео
# FIX-4: _is_within_lookback — защита от ms, будущего, до 2013
# FIX-5: воронка детализирует old по источнику (rss/inv/ytdlp)
# FIX-6: min_views/min_likes дефолт = 0 (верифицировано)
# ═══════════════════════════════════════════════════════════════════════════════

