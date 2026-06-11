"""
Модуль мониторинга YouTube для DayZ News Monitor.
Переработанная версия v2 — только ручные каналы.

Архитектура:
  1. Каналы загружаются из config.json (youtube_channels) — ТОЛЬКО вручную добавленные
  2. Для каждого канала через Invidious API берутся видео, сортированные по популярности
  3. Фильтруются шортсы (<=90с)
  4. Самый популярный шортс отправляется в AI для генерации Telegram-поста
  5. Пост уходит в очередь модерации (youtube_moderation.json)
  6. При одобрении в GUI: скачивание видео + публикация в Telegram
"""

import asyncio
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import aiohttp

from logger import logger


# ═════════════════════════════════════════════════════════════════════════════
#  Константы
# ═════════════════════════════════════════════════════════════════════════════

_SHORTS_MAX_DURATION = 90  # Порог для шортсов (секунды)

# Путь к файлу состояния (уже опубликованные / в модерации)
_STATE_FILE = "youtube_state.json"

# Путь к файлу очереди модерации
_MODERATION_FILE = "youtube_moderation.json"

# Пул потоков для yt-dlp
_thread_pool = ThreadPoolExecutor(max_workers=4)

# User-Agent
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


# ═════════════════════════════════════════════════════════════════════════════
#  HTTP сессия
# ═════════════════════════════════════════════════════════════════════════════

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


# yt-dlp семафор
_ytdlp_semaphore: asyncio.Semaphore | None = None


async def _get_ytdlp_semaphore() -> asyncio.Semaphore:
    global _ytdlp_semaphore
    if _ytdlp_semaphore is None:
        _ytdlp_semaphore = asyncio.Semaphore(4)
    return _ytdlp_semaphore


# ═════════════════════════════════════════════════════════════════════════════
#  Каналы (только ручные, из config.json)
# ═════════════════════════════════════════════════════════════════════════════

_YOUTUBE_CHANNELS: list[dict] = []


def load_youtube_channels(config: dict | None = None) -> list[dict]:
    """Загружает список каналов из config.json. Нет каналов = бот ничего не делает."""
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
    _YOUTUBE_CHANNELS = []
    return []


# ═════════════════════════════════════════════════════════════════════════════
#  Invidious инстансы
# ═════════════════════════════════════════════════════════════════════════════

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

_dynamic_instances: list[str] = []
_dynamic_instances_timestamp: float = 0.0
_DYNAMIC_CACHE_TTL = 6 * 3600


async def _fetch_dynamic_instances() -> list[str]:
    global _dynamic_instances, _dynamic_instances_timestamp
    now = time.time()
    if _dynamic_instances and (now - _dynamic_instances_timestamp) < _DYNAMIC_CACHE_TTL:
        return _dynamic_instances
    try:
        session = await _get_session()
        async with session.get("https://api.invidious.io/instances.json") as response:
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
    except Exception as e:
        logger.debug("YouTube: ошибка загрузки Invidious инстансов: %s", e)
    return _dynamic_instances


async def _get_invidious_instances() -> list[str]:
    dynamic = await _fetch_dynamic_instances()
    all_instances = list(dynamic)
    for inst in _STATIC_INVIDIOUS_INSTANCES:
        if inst not in all_instances:
            all_instances.append(inst)
    return all_instances


def _remove_bad_instance(instance_url: str) -> None:
    _dynamic_instances[:] = [inst for inst in _dynamic_instances if inst != instance_url]


# ═════════════════════════════════════════════════════════════════════════════
#  Утилиты
# ═════════════════════════════════════════════════════════════════════════════

def _format_duration(seconds: int | float) -> str:
    if not seconds or seconds <= 0:
        return "0:00"
    seconds = int(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _format_views(views: int) -> str:
    if views >= 1_000_000:
        return f"{views / 1_000_000:.1f}M"
    if views >= 1_000:
        return f"{views / 1_000:.1f}K"
    return str(views)


def _escape_html(text: str) -> str:
    if not text:
        return ""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    return text


def _detect_category(title: str, description: str = "") -> str:
    """Определяет категорию видео по ключевым словам."""
    text = f"{title} {description}".lower()
    keywords_map = {
        "guide": ["гайд", "обзор", "how to", "tutorial", "инструкция", "крафт", "лут", "спавн"],
        "pvp": ["pvp", "пвп", "рейд", "raid", "бой", "убийство", "kill", "камп"],
        "weapons": ["оружие", "weapon", "пушка", "винтовка", "пистолет", "дробовик", "патроны"],
        "vehicles": ["машина", "car", "вертолёт", "лодка", "транспорт"],
        "base": ["база", "base", "строительство", "стройка"],
        "bugs": ["баг", "bug", "глюк", "exploit", "чит", "хак"],
        "updates": ["обновление", "update", "патч", "новое", "версия"],
        "events": ["ивент", "event", "турнир", "вайп", "wipe"],
        "memes": ["мем", "meme", "прикол", "funny", "кринж", "shitpost"],
        "secrets": ["секрет", "пасхалка", "easter egg", "скрытое"],
    }
    best = "other"
    best_count = 0
    for cat, kws in keywords_map.items():
        count = sum(1 for kw in kws if kw.lower() in text)
        if count > best_count:
            best_count = count
            best = cat
    return best


def format_video_message(video: dict, category: str = "") -> str:
    """Форматирует информацию о видео в текст для Telegram."""
    title = _escape_html(video.get("title", "Без названия"))
    ch_title = _escape_html(video.get("channel_title", "YouTube"))
    duration = _format_duration(video.get("duration", 0))
    views = _format_views(video.get("views", 0))
    url = video.get("url", "")
    dur = video.get("duration", 0) or 0

    if dur <= _SHORTS_MAX_DURATION:
        content_type = "\U0001f4f1 Shorts"
    elif dur <= 180:
        content_type = "\U0001f3ac Видео"
    else:
        content_type = "\U0001f4f9 Длинное"

    lines = [
        f"{content_type} <b>{title}</b>",
        f"\U0001f4fa {ch_title}",
        f"\u23f1 {duration}  \U0001f441 {views}",
    ]
    if url:
        lines.append(url)
    return "\n".join(lines)


def cleanup_old_downloads(downloads_dir: str = "downloads", max_age_hours: int = 48) -> int:
    if not os.path.isdir(downloads_dir):
        return 0
    now = time.time()
    max_age = max_age_hours * 3600
    removed = 0
    for filename in os.listdir(downloads_dir):
        filepath = os.path.join(downloads_dir, filename)
        if os.path.isfile(filepath):
            try:
                if now - os.path.getmtime(filepath) > max_age:
                    os.remove(filepath)
                    removed += 1
            except OSError:
                continue
    if removed:
        logger.info("YouTube: удалено %d старых файлов", removed)
    return removed


# ═════════════════════════════════════════════════════════════════════════════
#  Управление состоянием
# ═════════════════════════════════════════════════════════════════════════════

def _save_state(state: dict) -> None:
    for target in [_STATE_FILE, f"/tmp/{_STATE_FILE}"]:
        try:
            with open(target, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
            return
        except OSError:
            continue


def _load_state() -> dict:
    for target in [_STATE_FILE, f"/tmp/{_STATE_FILE}"]:
        try:
            if os.path.exists(target):
                with open(target, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if "posted_ids" not in data:
                    data["posted_ids"] = {}
                return data
        except (json.JSONDecodeError, OSError):
            continue
    return {"posted_ids": {}, "last_check": 0}


# ═════════════════════════════════════════════════════════════════════════════
#  Очередь модерации
# ═════════════════════════════════════════════════════════════════════════════

_moderation_lock = threading.Lock()


def _load_moderation_queue() -> list[dict]:
    """Загружает очередь модерации из JSON файла."""
    with _moderation_lock:
        try:
            if os.path.exists(_MODERATION_FILE):
                with open(_MODERATION_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
        return []


def _save_moderation_queue(queue: list[dict]) -> None:
    """Сохраняет очередь модерации в JSON файл."""
    with _moderation_lock:
        try:
            with open(_MODERATION_FILE, "w", encoding="utf-8") as f:
                json.dump(queue, f, ensure_ascii=False, indent=2)
        except OSError as e:
            logger.error("Ошибка сохранения модерации: %s", e)


def get_pending_moderation() -> list[dict]:
    """Возвращает ожидающие модерации видео (для GUI)."""
    queue = _load_moderation_queue()
    return [item for item in queue if item.get("status") == "pending"]


def approve_video(video_id: str) -> bool:
    """Одобряет видео в очереди модерации (вызывается из GUI)."""
    queue = _load_moderation_queue()
    found = False
    for item in queue:
        if item.get("video_id") == video_id and item.get("status") == "pending":
            item["status"] = "approved"
            item["moderated_at"] = datetime.now(timezone.utc).isoformat()
            found = True
            break
    if found:
        _save_moderation_queue(queue)
        logger.info("YouTube модерация: видео %s ОДОБРЕНО", video_id)
    return found


def reject_video(video_id: str) -> bool:
    """Отклоняет видео в очереди модерации (вызывается из GUI)."""
    queue = _load_moderation_queue()
    found = False
    for item in queue:
        if item.get("video_id") == video_id and item.get("status") == "pending":
            item["status"] = "rejected"
            item["moderated_at"] = datetime.now(timezone.utc).isoformat()
            found = True
            break
    if found:
        _save_moderation_queue(queue)
        logger.info("YouTube модерация: видео %s ОТКЛОНЕНО", video_id)
    return found


def _add_to_moderation(
    video: dict,
    ai_post: str,
    ai_summary: str,
    category: str,
    priority: str,
) -> None:
    """Добавляет видео в очередь модерации со статусом 'pending'."""
    queue = _load_moderation_queue()
    queue.append({
        "video_id": video.get("video_id", ""),
        "title": video.get("title", ""),
        "channel_title": video.get("channel_title", ""),
        "channel_id": video.get("channel_id", ""),
        "duration": video.get("duration", 0),
        "views": video.get("views", 0),
        "likes": video.get("likes", 0),
        "url": video.get("url", ""),
        "thumbnail": video.get("thumbnail", ""),
        "ai_post": ai_post,
        "ai_summary": ai_summary,
        "category": category,
        "priority": priority,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "moderated_at": None,
        "video_data": {
            "video_id": video.get("video_id", ""),
            "title": video.get("title", ""),
            "channel_title": video.get("channel_title", ""),
            "channel_id": video.get("channel_id", ""),
            "duration": video.get("duration", 0),
            "views": video.get("views", 0),
            "likes": video.get("likes", 0),
            "url": video.get("url", ""),
            "thumbnail": video.get("thumbnail", ""),
            "description": (video.get("description", "") or "")[:1000],
            "published": video.get("published", 0),
        },
    })
    _save_moderation_queue(queue)
    logger.info(
        "YouTube модерация: видео %s добавлено в очередь (AI: %s, %s)",
        video.get("video_id", "?")[:12], category, priority,
    )


# ═════════════════════════════════════════════════════════════════════════════
#  Invidious: парсинг и получение видео каналов
# ═════════════════════════════════════════════════════════════════════════════

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


async def _resolve_handle_to_id(handle: str) -> str:
    """Резолвит @handle в UC... Channel ID через Invidious API."""
    if not handle.startswith("@"):
        return handle
    clean_handle = handle.lstrip("@")
    instances = await _get_invidious_instances()
    for inst in instances[:5]:
        try:
            session = await _get_session()
            async with session.get(
                f"{inst}/api/v1/resolveurl",
                params={"url": f"https://www.youtube.com/@{clean_handle}"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    _remove_bad_instance(inst)
                    continue
                data = await resp.json()
                ucid = data.get("ucid", "")
                author = data.get("author", "")
                if ucid and ucid.startswith("UC"):
                    logger.info("YouTube: @%s → %s (%s)", clean_handle, ucid, author)
                    # Обновляем ID в _YOUTUBE_CHANNELS на месте
                    for ch in _YOUTUBE_CHANNELS:
                        if ch.get("id") == handle:
                            ch["id"] = ucid
                            if not ch.get("name") and author:
                                ch["name"] = author
                            break
                    return ucid
        except Exception as e:
            logger.debug("YouTube: resolve @%s через %s ошибка: %s", clean_handle, inst, e)
            _remove_bad_instance(inst)
    logger.warning("YouTube: не удалось резолвить @%s в UC ID", clean_handle)
    return ""


async def _fetch_channel_videos_invidious(
    channel_id: str,
    max_videos: int = 30,
    sort_by: str = "popular",
) -> list[dict]:
    """
    Получает видео канала через Invidious API.
    sort_by: 'popular', 'newest', 'oldest'
    """
    if channel_id.startswith("@"):
        resolved = await _resolve_handle_to_id(channel_id)
        if resolved:
            channel_id = resolved
        else:
            return []

    instances = await _get_invidious_instances()
    for inst in instances[:5]:
        try:
            session = await _get_session()
            async with session.get(
                f"{inst}/api/v1/channels/{channel_id}/videos",
                params={"sort_by": sort_by, "page": 1},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    _remove_bad_instance(inst)
                    continue
                items = await resp.json()
                videos = []
                for item in items[:max_videos]:
                    if not isinstance(item, dict) or item.get("type") != "video":
                        continue
                    video = _parse_invidious_item(item)
                    if video.get("video_id"):
                        videos.append(video)
                if videos:
                    logger.debug(
                        "YouTube/channel: %s → %d видео через %s (sort=%s)",
                        channel_id, len(videos), inst, sort_by,
                    )
                return videos
        except Exception as e:
            logger.debug("YouTube/channel: %s через %s ошибка: %s", channel_id, inst, e)
            _remove_bad_instance(inst)
    return []


async def _fetch_channel_best_short(
    channel_id: str,
    known_ids: set[str],
) -> dict | None:
    """
    Находит самый популярный шортс с канала, которого ещё нет в known_ids.
    Возвращает видео dict или None.
    """
    videos = await _fetch_channel_videos_invidious(channel_id, max_videos=30, sort_by="popular")
    if not videos:
        return None

    # Фильтр: только шортсы + не стримы + не в known_ids
    shorts = []
    for v in videos:
        vid = v.get("video_id", "")
        dur = v.get("duration", 0) or 0
        if not vid or vid in known_ids:
            continue
        if dur > _SHORTS_MAX_DURATION:
            continue
        if v.get("is_live", False):
            continue
        shorts.append(v)

    if not shorts:
        return None

    # Сортировка: сначала по views, потом по likes
    shorts.sort(
        key=lambda v: ((v.get("views", 0) or 0), (v.get("likes", 0) or 0)),
        reverse=True,
    )
    return shorts[0]


# ═════════════════════════════════════════════════════════════════════════════
#  Скачивание видео
# ═════════════════════════════════════════════════════════════════════════════

def _download_ytdlp_sync(
    url: str,
    output_template: str,
    cookies_file: str = "",
    max_filesize: int = 50 * 1024 * 1024,
    _retry_with_fallback: bool = False,
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

    if _retry_with_fallback:
        format_str = "best"
    else:
        format_str = (
            "best[height<=720][ext=mp4]"
            "/best[ext=mp4]"
            "/best[height<=720]"
            "/best"
        )

    ydl_opts = {
        "format": format_str,
        "outtmpl": output_template,
        "max_filesize": max_filesize,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "nocheckcertificate": True,
        "merge_output_format": "mp4",
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
                if result_path and os.path.isfile(result_path):
                    if os.path.getsize(result_path) > 0:
                        return result_path
                    else:
                        try:
                            os.remove(result_path)
                        except OSError:
                            pass
                        return None
            video_id = info.get("id", "unknown")
            result_path = output_template.replace("%(id)s", video_id)
            if result_path and os.path.isfile(result_path) and os.path.getsize(result_path) > 0:
                return result_path
    except Exception as e:
        err_str = str(e)
        if "Sign in to confirm" in err_str or "bot" in err_str.lower():
            logger.warning("YouTube/download: YouTube требует cookies для '%s'", url)
        elif "ffmpeg" in err_str.lower() or "exited with code" in err_str.lower():
            logger.warning("YouTube/download: ffmpeg ошибка (%s), пробую простой формат", err_str[:120])
            if not _retry_with_fallback:
                return _download_ytdlp_sync(
                    url, output_template, cookies_file, max_filesize,
                    _retry_with_fallback=True,
                )
        else:
            logger.debug("YouTube/download: yt-dlp ошибка: %s", e)

    return None


async def download_short(
    video: dict,
    downloads_dir: str = "downloads",
    max_filesize_mb: int = 50,
) -> str | None:
    """Скачивает шортс с YouTube."""
    url = video.get("url", "")
    if not url:
        return None

    os.makedirs(downloads_dir, exist_ok=True)
    output_template = os.path.join(downloads_dir, "%(id)s.%(ext)s")
    max_filesize = max_filesize_mb * 1024 * 1024

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
                   ". Нужен cookies.txt" if not os.path.isfile(cookies_path) else "")
    return None


# ═════════════════════════════════════════════════════════════════════════════
#  Основная логика
# ═════════════════════════════════════════════════════════════════════════════

async def check_for_popular_shorts(
    config: dict | None = None,
    ai_analyzer=None,
) -> list[dict]:
    """
    Проверяет каналы на наличие популярных шортсов.

    Для каждого канала:
      1. Получает видео через Invidious (sort_by=popular)
      2. Фильтрует шортсы (<=90с)
      3. Берёт самый популярный, которого ещё не было
      4. Отправляет в AI для генерации поста
      5. Добавляет в очередь модерации

    Returns: список найденных новых видео.
    """
    if config is None:
        config = {}

    channels = load_youtube_channels(config)
    if not channels:
        logger.info("YouTube: нет каналов для парсинга (добавьте через GUI)")
        return []

    # Собираем все известные ID (опубликованные + в модерации)
    state = _load_state()
    posted_ids = set(state.get("posted_ids", {}).keys())
    moderation_queue = _load_moderation_queue()
    moderation_ids = {item.get("video_id") for item in moderation_queue if item.get("video_id")}
    known_ids = posted_ids | moderation_ids

    new_videos = []
    start = time.time()

    for ch in channels:
        ch_id = ch.get("id", "")
        ch_name = ch.get("name", ch_id)
        if not ch_id:
            continue

        try:
            best = await _fetch_channel_best_short(ch_id, known_ids)
            if not best:
                logger.debug("YouTube: на канале %s нет новых шортсов", ch_name)
                continue

            video_id = best.get("video_id", "")
            views = best.get("views", 0) or 0
            likes = best.get("likes", 0) or 0
            dur = best.get("duration", 0) or 0

            logger.info(
                "YouTube [+]: '%s' (%s, %s, %s views, %s likes) от %s",
                best.get("title", "")[:60], _format_duration(dur),
                _format_views(views), _format_views(views),
                _format_views(likes), ch_name,
            )

            # AI генерация поста
            ai_post = ""
            ai_summary = ""
            category = "other"
            priority = "low"

            if ai_analyzer:
                try:
                    category = _detect_category(best.get("title", ""), best.get("description", ""))
                    best["category"] = category
                    ai_result = await ai_analyzer.analyze_youtube_video(best)
                    if ai_result:
                        ai_post = ai_result.get("formatted_post", "") or ""
                        ai_summary = ai_result.get("summary", "") or ""
                        category = ai_result.get("news_type", category) or category
                        priority = ai_result.get("priority", "low") or "low"
                        logger.info("YouTube AI: '%s' → %s (%s)",
                                    best.get("title", "")[:40], category, priority)
                except Exception as e:
                    logger.debug("YouTube: AI недоступен: %s", e)

            # Фоллбэк если AI не сработал
            if not ai_post:
                ai_post = format_video_message(best, category)
                ai_summary = best.get("title", "")

            # Добавляем в модерацию
            _add_to_moderation(best, ai_post, ai_summary, category, priority)

            # Отмечаем чтобы не повторять
            known_ids.add(video_id)
            posted_ids[video_id] = {
                "title": best.get("title", "")[:200],
                "timestamp": time.time(),
                "status": "moderation",
                "channel": ch_name,
            }
            new_videos.append(best)

        except Exception as e:
            logger.error("YouTube: ошибка канала %s: %s", ch_name, e)

    # Сохраняем состояние
    state["posted_ids"] = posted_ids
    state["last_check"] = time.time()
    _save_state(state)

    elapsed = time.time() - start
    if new_videos:
        logger.info(
            "YouTube: %d шортсов отправлено на модерацию (%d каналов, %.1fс)",
            len(new_videos), len(channels), elapsed,
        )
    else:
        logger.info(
            "YouTube: новых шортсов не найдено (%d каналов, %.1fс)",
            len(channels), elapsed,
        )

    return new_videos


async def _process_approved_videos(config: dict, publisher=None) -> None:
    """
    Обрабатывает одобренные видео: скачивает и публикует в Telegram.
    Вызывается из event loop бота.
    """
    queue = _load_moderation_queue()
    approved = [item for item in queue if item.get("status") == "approved"]

    if not approved:
        return

    for item in approved:
        video_id = item.get("video_id", "")
        video_data = item.get("video_data", {})
        ai_post = item.get("ai_post", "")

        logger.info("YouTube: обрабатываю одобрение для %s — скачиваю...", video_id)

        # Скачивание
        downloads_dir = config.get("images_dir", "downloads")
        filepath = await download_short(video_data, downloads_dir=downloads_dir)

        if filepath and publisher and ai_post:
            # Публикация с видео
            try:
                tg_msg_id = await publisher.publish_message(
                    text=ai_post,
                    video_paths=[filepath],
                )
                if tg_msg_id:
                    logger.info("YouTube: видео %s ОПУБЛИКОВАНО (TG msg_id=%d)", video_id, tg_msg_id)
                    item["status"] = "published"
                    item["tg_message_id"] = tg_msg_id
                    item["published_at"] = datetime.now(timezone.utc).isoformat()
                else:
                    logger.error("YouTube: не удалось опубликовать %s", video_id)
                    item["status"] = "publish_failed"
            except Exception as e:
                logger.error("YouTube: ошибка публикации %s: %s", video_id, e)
                item["status"] = "publish_failed"
        elif not filepath:
            logger.warning("YouTube: не удалось скачать %s для публикации", video_id)
            item["status"] = "download_failed"
        else:
            item["status"] = "no_publisher"

        item["moderated_at"] = datetime.now(timezone.utc).isoformat()

    _save_moderation_queue(queue)


# ═════════════════════════════════════════════════════════════════════════════
#  Постоянный мониторинг (фоновая задача)
# ═════════════════════════════════════════════════════════════════════════════

async def run_youtube_monitor(
    db=None,
    ai_analyzer=None,
    check_interval_hours: int = 2,
    shutdown_event=None,
    publisher=None,
    config: dict | None = None,
) -> None:
    """
    Запускает постоянный мониторинг YouTube Shorts.

    Логика:
      - Каждые check_interval_hours проверяет каналы на популярные шортсы
      - Каждые 30 секунд проверяет одобренные видео для скачивания+публикации

    Args:
        db: Экземпляр Database (для совместимости).
        ai_analyzer: AI анализатор для генерации постов.
        check_interval_hours: Интервал проверки каналов (часы).
        shutdown_event: asyncio.Event для остановки.
        publisher: Publisher для публикации в Telegram.
        config: Конфигурация бота.
    """
    if check_interval_hours < 1:
        check_interval_hours = 1

    logger.info(
        "YouTube монитор v2: запущен (интервал=%dч, только ручные каналы, модерация)",
        check_interval_hours,
    )

    approval_check_seconds = 30

    while True:
        if shutdown_event and shutdown_event.is_set():
            logger.info("YouTube монитор: остановлен")
            break

        try:
            # Основная проверка: ищем популярные шортсы
            await check_for_popular_shorts(config=config, ai_analyzer=ai_analyzer)

            # Проверяем одобренные (скачивание + публикация)
            if publisher:
                await _process_approved_videos(config or {}, publisher)

            # Очистка
            cleanup_old_downloads()

        except Exception as e:
            logger.error("YouTube монитор: критическая ошибка: %s", e)

        # Ожидание с периодической проверкой одобрений
        wait_seconds = check_interval_hours * 3600
        while wait_seconds > 0:
            if shutdown_event and shutdown_event.is_set():
                logger.info("YouTube монитор: остановлен")
                # Закрываем сессию
                if _http_session and not _http_session.closed:
                    await _http_session.close()
                return

            chunk = min(approval_check_seconds, wait_seconds)
            await asyncio.sleep(chunk)
            wait_seconds -= chunk

            # Каждые 30с — проверяем одобрения (даже между основными проверками)
            if publisher:
                try:
                    await _process_approved_videos(config or {}, publisher)
                except Exception:
                    pass


# ═════════════════════════════════════════════════════════════════════════════
#  Standalone запуск
# ═════════════════════════════════════════════════════════════════════════════

async def main():
    """Standalone запуск для тестирования."""
    config_path = os.environ.get("CONFIG_PATH", "config.json")
    config = {}
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except FileNotFoundError:
        logger.warning("config.json не найден")

    logger.info("YouTube монитор v2: standalone режим")
    videos = await check_for_popular_shorts(config=config)

    if videos:
        logger.info("YouTube: найдено %d шортсов", len(videos))
        for v in videos:
            print(format_video_message(v, v.get("category", "")))
            print("─" * 60)
    else:
        logger.info("YouTube: новых шортсов не найдено")