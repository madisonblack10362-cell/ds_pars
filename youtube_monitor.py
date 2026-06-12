"""
Модуль мониторинга YouTube для DayZ News Monitor.
Переработанная версия v3 — yt-dlp напрямую (без Invidious).

Архитектура:
  1. Каналы загружаются из config.json (youtube_channels) — ТОЛЬКО вручную добавленные
  2. Для каждого канала через yt-dlp (extract_flat) берутся видео
  3. Фильтруются шортсы (<=180с), сортируются по просмотрам
  4. Самый популярный шортс скачивается СРАЗУ
  5. Отправляется в AI для генерации Telegram-поста
  6. Пост с видео уходит в очередь модерации (youtube_moderation.json)
  7. Уведомление в Telegram с видео прикреплённым
  8. При одобрении: публикация в Telegram (видео уже скачано)

Зависимости для скачивания:
  - yt-dlp (pip install yt-dlp)
  - ffmpeg (для мержа видео+аудио)
"""

import asyncio
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from logger import logger


# ═════════════════════════════════════════════════════════════════════════════
#  Константы
# ═════════════════════════════════════════════════════════════════════════════

_SHORTS_MAX_DURATION = 180  # Порог для шортсов (секунды, YouTube допускает до 3 мин)

# Путь к файлу состояния (уже опубликованные / в модерации)
_STATE_FILE = "youtube_state.json"

# Путь к файлу очереди модерации
_MODERATION_FILE = "youtube_moderation.json"

# Пул потоков для yt-dlp
_thread_pool = ThreadPoolExecutor(max_workers=4)


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
    """Возвращает ожидающие модерации видео (для веб-панели)."""
    queue = _load_moderation_queue()
    return [item for item in queue if item.get("status") == "pending"]


def approve_video(video_id: str) -> bool:
    """Одобряет видео в очереди модерации (вызывается из веб-панели)."""
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
    """Отклоняет видео в очереди модерации (вызывается из веб-панели)."""
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
    downloaded_file: str = "",
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
        "downloaded_file": downloaded_file,
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
#  Получение видео через yt-dlp (напрямую, без Invidious)
# ═════════════════════════════════════════════════════════════════════════════

async def _fetch_channel_videos(
    channel_input: str,
    max_videos: int = 30,
) -> tuple[list[dict], str, str]:
    """
    Получает видео канала через yt-dlp CLI (flat playlist — быстрый список).
    """
    if "youtube.com" in channel_input:
        url = channel_input if "/videos" in channel_input else channel_input.rstrip("/") + "/videos"
    elif channel_input.startswith("@"):
        url = f"https://www.youtube.com/{channel_input}/videos"
    elif channel_input.startswith("UC"):
        url = f"https://www.youtube.com/channel/{channel_input}/videos"
    else:
        url = f"https://www.youtube.com/{channel_input}/videos"

    loop = asyncio.get_running_loop()

    def _fetch_sync():
        import subprocess
        import shutil

        ytdlp_cmd = shutil.which("yt-dlp")
        if ytdlp_cmd:
            cmd = [ytdlp_cmd, "-4", "--no-config", "--flat-playlist", "--dump-json", "--quiet", "--no-warnings", url]
        else:
            cmd = [sys.executable, "-m", "yt_dlp", "-4", "--no-config", "--flat-playlist", "--dump-json",
                   "--quiet", "--no-warnings", url]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode != 0 or not result.stdout.strip():
                logger.warning("YouTube/ytdlp: %s — видео не получены", channel_input)
                return [], "", ""

            videos = []
            channel_id = ""
            channel_name = ""

            for line in result.stdout.strip().split("\n")[:max_videos]:
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if not channel_id:
                    channel_id = entry.get("channel_id", "") or ""
                if not channel_name:
                    channel_name = (entry.get("uploader") or entry.get("channel", "")).strip()

                vid = entry.get("id", "")
                if not vid:
                    continue

                videos.append({
                    "video_id": vid,
                    "title": (entry.get("title") or "").strip(),
                    "channel_title": channel_name,
                    "channel_id": channel_id,
                    "duration": 0,
                    "views": 0,
                    "likes": 0,
                    "published": entry.get("timestamp", 0) or 0,
                    "description": "",
                    "thumbnail": entry.get("thumbnail", ""),
                    "url": f"https://www.youtube.com/watch?v={vid}",
                    "is_live": entry.get("live_status") == "is_live",
                    "source": "ytdlp",
                })

            return videos, channel_id, channel_name

        except subprocess.TimeoutExpired:
            logger.warning("YouTube/ytdlp: таймаут списка видео для %s", channel_input)
            return [], "", ""
        except Exception as e:
            logger.error("YouTube/ytdlp: %s -> %s", channel_input, e)
            return [], "", ""

    videos, channel_id, channel_name = await loop.run_in_executor(_thread_pool, _fetch_sync)

    if videos:
        shorts_count = sum(1 for v in videos if (v.get("duration", 0) or 0) <= _SHORTS_MAX_DURATION)
        logger.info(
            "YouTube/ytdlp: %s -> %d видео, %d shorts (%s)",
            channel_input, len(videos), shorts_count, channel_name or channel_id,
        )
        # Обновляем ID и имя канала в _YOUTUBE_CHANNELS
        if channel_id and channel_id != channel_input:
            for ch in _YOUTUBE_CHANNELS:
                if ch.get("id") == channel_input:
                    ch["id"] = channel_id
                    if channel_name and not ch.get("name"):
                        ch["name"] = channel_name
                    logger.info("YouTube: %s -> %s (%s)", channel_input, channel_id, channel_name)
                    break
    else:
        logger.warning("YouTube/ytdlp: %s — видео не получены", channel_input)

    return videos, channel_id, channel_name


def _enrich_video_metadata_sync(video: dict) -> dict:
    """Синхронная версия — вызывается из executor."""
    url = video.get("url", "")
    video_id = video.get("video_id", "")
    if not url:
        return video

    import subprocess
    import shutil

    script_dir = os.path.dirname(os.path.abspath(__file__))
    cookies_path = os.path.join(script_dir, "cookies.txt")

    ytdlp_cmd = shutil.which("yt-dlp")
    base = [ytdlp_cmd] if ytdlp_cmd else [sys.executable, "-m", "yt_dlp"]

    # android_vr — не нужен PO token, cookies, логин. Самый надёжный.
    # -4 — IPv4 (YouTube агрессивнее блокирует IPv6)
    attempts = []

    # 1) android_vr (лучший для без-cookie)
    attempts.append((base + [
        "-4", "--no-config", "--dump-json", "--no-download", "--quiet", "--no-warnings",
        "--extractor-args", "youtube:player_client=android_vr",
        url,
    ], "android_vr"))

    # 2) ios (без PO token, но иногда format issues)
    attempts.append((base + [
        "-4", "--no-config", "--dump-json", "--no-download", "--quiet", "--no-warnings",
        "--extractor-args", "youtube:player_client=ios",
        url,
    ], "ios"))

    # 3) С cookies если есть
    if os.path.isfile(cookies_path):
        attempts.append((base + [
            "-4", "--no-config", "--dump-json", "--no-download", "--quiet", "--no-warnings",
            "--cookies", cookies_path,
            url,
        ], "cookies"))

    last_result = None
    for cmd, label in attempts:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            last_result = result
            if result.returncode == 0 and result.stdout.strip():
                info = json.loads(result.stdout)
                video["description"] = (info.get("description") or "")[:2000]
                video["views"] = info.get("view_count") or video.get("views", 0) or 0
                video["likes"] = info.get("like_count") or video.get("likes", 0) or 0
                video["duration"] = int(info.get("duration") or video.get("duration", 0) or 0)
                thumb = info.get("thumbnail") or ""
                if thumb:
                    video["thumbnail"] = thumb
                logger.info(
                    "YouTube: метаданные %s — %s views, %s likes, %s (попытка: %s)",
                    video_id[:12],
                    _format_views(video["views"]), _format_views(video["likes"]),
                    _format_duration(video["duration"]), label,
                )
                return video
        except subprocess.TimeoutExpired:
            continue
        except json.JSONDecodeError:
            continue
        except Exception:
            continue

    # Все попытки провалились — логируем последнюю ошибку
    stderr_snippet = ""
    if last_result and last_result.stderr:
        stderr_snippet = last_result.stderr[:300].replace("\n", " | ")
    logger.warning("YouTube: yt-dlp не смог получить метаданные %s (stderr: %s)",
                   video_id[:12], stderr_snippet)

    return video


async def _enrich_video_metadata(video: dict) -> dict:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_thread_pool, _enrich_video_metadata_sync, video)


def _fetch_channel_best_short_sync(
    channel_id: str,
    known_ids: set[str],
    max_candidates: int = 1,
) -> dict | None:
    """
    Полностью синхронная версия — без asyncio внутри.
    Вызывается из run_in_executor.
    """
    import subprocess
    import shutil

    # Строим URL канала
    if "youtube.com" in channel_id:
        url = channel_id if "/shorts" in channel_id else channel_id.rstrip("/") + "/shorts"
    elif channel_id.startswith("@"):
        url = f"https://www.youtube.com/{channel_id}/shorts"
    elif channel_id.startswith("UC"):
        url = f"https://www.youtube.com/channel/{channel_id}/shorts"
    else:
        url = f"https://www.youtube.com/{channel_id}/shorts"

    ytdlp_cmd = shutil.which("yt-dlp")
    base_cmd = [ytdlp_cmd] if ytdlp_cmd else [sys.executable, "-m", "yt_dlp"]

    # Шаг 1: flat-playlist — быстрый список
    cmd = base_cmd + [
        "-4", "--no-config", "--flat-playlist", "--dump-json", "--quiet", "--no-warnings", url
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        logger.warning("YouTube/ytdlp: таймаут списка видео для %s", channel_id)
        return None
    except Exception as e:
        logger.error("YouTube/ytdlp: %s -> %s", channel_id, e)
        return None

    if result.returncode != 0 or not result.stdout.strip():
        logger.warning("YouTube/ytdlp: %s — видео не получены", channel_id)
        return None

    # Парсим список
    candidates = []
    channel_name = ""
    ch_id_from_feed = ""
    for line in result.stdout.strip().split("\n")[:30]:
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not channel_name:
            channel_name = (entry.get("uploader") or entry.get("channel", "")).strip()
        if not ch_id_from_feed:
            ch_id_from_feed = entry.get("channel_id", "") or ""
        vid = entry.get("id", "")
        if not vid or vid in known_ids:
            continue
        if entry.get("live_status") == "is_live":
            continue
        candidates.append({
            "video_id": vid,
            "title": (entry.get("title") or "").strip(),
            "channel_title": channel_name,
            "channel_id": ch_id_from_feed,
            "duration": 0,
            "views": 0,
            "likes": 0,
            "published": entry.get("timestamp", 0) or 0,
            "description": "",
            "thumbnail": entry.get("thumbnail", ""),
            "url": f"https://www.youtube.com/watch?v={vid}",
            "is_live": False,
            "source": "ytdlp",
        })

    if not candidates:
        logger.info("YouTube: на канале нет новых видео (канал: %s)", channel_id)
        return None

    # Шаг 2: обогащаем метаданными кандидатов (чистый sync!)
    shorts = []
    for candidate in candidates[:max_candidates]:
        enriched = _enrich_video_metadata_sync(candidate)
        dur = enriched.get("duration", 0) or 0
        if dur <= _SHORTS_MAX_DURATION:
            shorts.append(enriched)

    if not shorts:
        logger.info("YouTube: на канале нет новых шортсов (проверено %d)", min(len(candidates), 5))
        return None

    # Сортировка: сначала по views, потом по likes
    shorts.sort(
        key=lambda v: ((v.get("views", 0) or 0), (v.get("likes", 0) or 0)),
        reverse=True,
    )
    return shorts[0]


async def _fetch_channel_best_short(
    channel_id: str,
    known_ids: set[str],
    max_candidates: int = 1,
) -> dict | None:
    """Async-обёртка над sync-версией."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _thread_pool,
        _fetch_channel_best_short_sync,
        channel_id,
        known_ids,
        max_candidates,
    )


# ═════════════════════════════════════════════════════════════════════════════
#  Скачивание видео
# ═════════════════════════════════════════════════════════════════════════════

def _build_ytdlp_base_cmd() -> list[str]:
    """Возвращает базовую команду: yt-dlp бинарник если есть, иначе python -m yt_dlp."""
    import shutil
    ytdlp_cmd = shutil.which("yt-dlp")
    if ytdlp_cmd:
        return [ytdlp_cmd]
    return [sys.executable, "-m", "yt_dlp"]


def _download_ytdlp_sync(
    url: str,
    output_template: str,
    cookies_file: str = "",
    max_filesize: int = 50 * 1024 * 1024,
) -> str | None:
    """
    Скачивает видео через yt-dlp.
    Пробует несколько player_client по очереди.
    """
    import subprocess
    import shutil
    import glob as glob_mod

    base = _build_ytdlp_base_cmd()
    video_id = url.split("v=")[-1].split("&")[0]

    # Общие флаги для ВСЕХ попыток
    common_flags = [
        "-4", "--no-config",
        "--no-playlist",
        "--max-filesize", str(max_filesize),
    ]

    # Форматы: сначала mp4 720p, потом любой mp4, потом лучший
    format_variants = [
        "best[height<=720][ext=mp4]/best[ext=mp4]/best[height<=720]/best",
        "bestvideo[height<=720]+bestaudio/best[ext=mp4]/best",
        "best",
    ]

    # Player client варианты
    player_clients = ["android_vr", "ios", "mediaconnect"]
    if cookies_file and os.path.isfile(cookies_file):
        player_clients.append("_with_cookies")

    last_stderr = ""
    total_tried = 0

    for client in player_clients:
        for fmt in format_variants:
            total_tried += 1
            cmd = base + common_flags + [
                "-f", fmt,
                "-o", output_template,
                "--merge-output-format", "mp4",
                "--no-warnings",
            ]

            if client == "_with_cookies":
                cmd += ["--cookies", cookies_file]
            else:
                cmd += ["--extractor-args", f"youtube:player_client={client}"]

            cmd.append(url)

            try:
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=180,
                )
                last_stderr = (result.stderr or "")[:500]

                if result.returncode != 0:
                    stderr_full = last_stderr
                    stderr_line = stderr_full.strip().split("\n")[-1][:200]
                    logger.warning(
                        "YouTube/download: [%s + %s] rc=%d: %s",
                        client, fmt.split("/")[0], result.returncode, stderr_line,
                    )
                    # Ранний выход: видео недоступно
                    if "Video unavailable" in stderr_full or "video is unavailable" in stderr_full.lower():
                        logger.error("YouTube/download: видео %s НЕДОСТУПНО (удалено/приватное)", video_id)
                        return None
                    # Ранний выход: бот-детект (cookies не помогут, IP заблокирован)
                    if "Sign in to confirm" in stderr_full or "not a bot" in stderr_full.lower():
                        logger.error("YouTube/download: бот-детект для %s, нужны cookies", video_id)
                        # Но если есть cookies — не выходим, дойдём до _with_cookies попытки
                        if not (cookies_file and os.path.isfile(cookies_file)):
                            return None
                    # Файл слишком большой
                    if "File is larger than" in stderr_full or "max-filesize" in stderr_full:
                        logger.warning("YouTube/download: файл превышает %d MB, пропуск", max_filesize // (1024 * 1024))
                        return None
                    continue

                # Ищем скачанный файл
                # Сначала пробуем точное имя (mp4)
                for ext in ["mp4", "webm", "mkv", "3gp"]:
                    test_path = output_template.replace("%(ext)s", ext).replace("%(id)s", video_id)
                    if os.path.isfile(test_path) and os.path.getsize(test_path) > 0:
                        size_mb = os.path.getsize(test_path) / (1024 * 1024)
                        logger.info(
                            "YouTube/download: скачано [%s] -> %s (%.1f MB)",
                            client, os.path.basename(test_path), size_mb,
                        )
                        return test_path

                # Glob поиск
                pattern = output_template.replace("%(id)s", video_id).replace("%(ext)s", "*")
                for m in sorted(glob_mod.glob(pattern), key=os.path.getsize, reverse=True):
                    if os.path.isfile(m) and os.path.getsize(m) > 0:
                        size_mb = os.path.getsize(m) / (1024 * 1024)
                        logger.info(
                            "YouTube/download: скачано [%s, glob] -> %s (%.1f MB)",
                            client, os.path.basename(m), size_mb,
                        )
                        return m

            except subprocess.TimeoutExpired:
                logger.warning("YouTube/download: [%s] таймаут 180с", client)
                continue
            except Exception as e:
                logger.warning("YouTube/download: [%s] исключение: %s", client, e)
                continue

    # Все попытки провалились
    logger.error(
        "YouTube/download: НЕ СКАЧАЛ %s (пробовано %d комбинаций). Последняя ошибка: %s",
        video_id, total_tried,
        last_stderr.replace("\n", " | ")[:300] if last_stderr else "нет stderr",
    )
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
    return result


async def download_short_by_id(
    video_id: str,
    downloads_dir: str = "downloads",
    max_filesize_mb: int = 50,
) -> str | None:
    """Скачивает шортс по video_id (для публикации из веб-панели)."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    return await download_short(
        video={"url": url, "video_id": video_id},
        downloads_dir=downloads_dir,
        max_filesize_mb=max_filesize_mb,
    )


def download_short_sync(
    video_id: str,
    downloads_dir: str = "downloads",
    max_filesize_mb: int = 50,
) -> str | None:
    """Синхронная версия скачивания (для вызова из sync-кода)."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    if not url:
        return None
    os.makedirs(downloads_dir, exist_ok=True)
    output_template = os.path.join(downloads_dir, "%(id)s.%(ext)s")
    max_filesize = max_filesize_mb * 1024 * 1024
    script_dir = os.path.dirname(os.path.abspath(__file__))
    cookies_path = os.path.join(script_dir, "cookies.txt")
    return _download_ytdlp_sync(url, output_template, cookies_path, max_filesize)


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
      1. Получает видео через yt-dlp (extract_flat)
      2. Обогащает метаданными (views, likes, description)
      3. Фильтрует шортсы (<=180с)
      4. Берёт самый популярный, которого ещё не было
      5. СКАЧИВАЕТ ВИДЕО СРАЗУ (до AI и модерации)
      6. Отправляет в AI для генерации поста
      7. Отправляет на веб-панель для модерации (sourceType=youtube, downloaded_file в локальной очереди)

    Returns: список найденных новых видео.
    """
    if config is None:
        config = {}

    channels = load_youtube_channels(config)
    if not channels:
        logger.info("YouTube: нет каналов для парсинга (добавьте через GUI)")
        return []

    # Перемешиваем каналы рандомно — чтобы не всегда проверять первые
    import random
    random.shuffle(channels)

    # Собираем все известные ID (опубликованные + в модерации)
    state = _load_state()
    posted_ids = dict(state.get("posted_ids", {}))
    moderation_queue = _load_moderation_queue()
    moderation_ids = {item.get("video_id") for item in moderation_queue if item.get("video_id")}
    known_ids = set(posted_ids.keys()) | moderation_ids

    max_per_check = config.get("youtube_max_per_check", 1)

    new_videos = []
    start = time.time()

    for ch in channels:
        # Глобальный лимит — не больше max_per_check видео всего
        if len(new_videos) >= max_per_check:
            logger.info("YouTube: достигнут лимит %d видео, пропускаем остальные каналы", max_per_check)
            break

        ch_id = ch.get("id", "")
        ch_name = ch.get("name", ch_id)
        if not ch_id:
            continue

        try:
            best = await _fetch_channel_best_short(ch_id, known_ids, 1)
            if not best:
                continue

            video_id = best.get("video_id", "")
            views = best.get("views", 0) or 0
            likes = best.get("likes", 0) or 0
            dur = best.get("duration", 0) or 0

            logger.info(
                "YouTube [+]: '%s' (%s, %s views, %s likes) от %s",
                best.get("title", "")[:60], _format_duration(dur),
                _format_views(views), _format_views(likes), ch_name,
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
                        logger.info("YouTube AI: '%s' -> %s (%s)",
                                    best.get("title", "")[:40], category, priority)
                except Exception as e:
                    logger.warning("YouTube: AI ошибка: %s", e)

            # Фоллбэк если AI не сработал
            if not ai_post:
                ai_post = format_video_message(best, category)
                ai_summary = best.get("title", "")

            # Подпись-ссылка на канал в конце поста
            if ai_post and "t.me/dayzhub" not in ai_post:
                ai_post += f"\n\n\u00a9 <a href=\"https://t.me/dayzhub\">DayZ HUB</a> — подписывайся, чтобы не пропустить новости, гайды и обновления по DayZ \U0001f514"

            # ═══ Скачиваем видео СРАЗУ ═══
            # Если не скачалось — НИКУДА не отправляем (ни панель, ни бот, ни модерацию)
            downloads_dir = "downloads"
            downloaded_file = await download_short(best, downloads_dir=downloads_dir)

            if not downloaded_file or not os.path.isfile(downloaded_file):
                logger.error(
                    "YouTube: ПРОПУСК %s — видео НЕ скачалось, не отправляю в панель/бот",
                    video_id[:12],
                )
                # Сохраняем ID чтобы не пытаться каждый цикл
                known_ids.add(video_id)
                posted_ids[video_id] = {
                    "title": best.get("title", "")[:200],
                    "timestamp": time.time(),
                    "status": "download_failed",
                    "channel": ch_name,
                }
                continue  # следующий канал

            # ═══ Видео скачано — отправляем в модерацию, панель, бот ═══
            logger.info("YouTube: видео %s скачано успешно, отправляю на модерацию", video_id[:12])

            # Добавляем в локальную очередь модерации (с путём к файлу)
            _add_to_moderation(best, ai_post, ai_summary, category, priority,
                              downloaded_file=downloaded_file)

            # Отправляем на веб-панель для модерации
            web_panel_url = config.get("web_panel_url", "")
            web_panel_api_key = config.get("web_panel_api_key", "")
            if web_panel_url:
                try:
                    from web_app_integration import send_to_web_panel

                    # НЕ отправляем thumbnail как фото — это видео, не картинка
                    youtube_url = best.get("url", "")

                    success = await send_to_web_panel(
                        news_data={
                            "sourceId": "youtube",
                            "externalId": f"yt_{video_id}",
                            "serverName": ch_name,
                            "channelName": f"YouTube: {ch_name}",
                            "content": f"{best.get('title', '')}\n\nКанал: {ch_name}\nДлительность: {_format_duration(dur)}\nПросмотры: {_format_views(views)}\nЛайки: {_format_views(likes)}",
                            "summary": ai_summary,
                            "formattedPost": ai_post,
                            "newsType": category,
                            "priority": priority,
                            "images": [],
                            "links": [youtube_url] if youtube_url else [],
                            "sourceType": "youtube",
                        },
                        web_app_url=web_panel_url,
                        bot_api_key=web_panel_api_key or None,
                    )
                    if success:
                        logger.info("YouTube: видео %s отправлено на веб-панель", video_id[:12])
                    else:
                        logger.warning("YouTube: не удалось отправить %s на веб-панель", video_id[:12])
                except Exception as web_err:
                    logger.error("YouTube: ошибка отправки на веб-панель: %s", web_err)

            # Уведомление в Telegram — с видео прикреплённым
            try:
                notify_chat_id = config.get("telegram_notify_chat_id", "") or config.get("telegram_channel_id", "")
                bot_token = config.get("telegram_bot_token", "")
                if notify_chat_id and bot_token:
                    import httpx
                    type_icons = {
                        "update": "🎮", "wipe": "🔄", "patch": "🔧", "event": "📅",
                        "guide": "📖", "pvp": "⚔️", "weapons": "🔫", "memes": "😂",
                        "other": "📰",
                    }
                    icon = type_icons.get(category, "📰")
                    prio_labels = {"high": "🔴", "medium": "🟡", "low": "🟢"}
                    prio_icon = prio_labels.get(priority, "")
                    text = (
                        f"{prio_icon} <b>YouTube модерация</b> 📺\n"
                        f"{'━' * 20}\n"
                        f"<b>{_escape_html(best.get('title', '')[:80])}</b>\n"
                        f"⏱ {_format_duration(dur)}  👁 {_format_views(views)}"
                    )
                    async with httpx.AsyncClient(timeout=30) as client:
                        with open(downloaded_file, "rb") as vf:
                            await client.post(
                                f"https://api.telegram.org/bot{bot_token}/sendVideo",
                                data={
                                    "chat_id": int(notify_chat_id),
                                    "caption": text,
                                    "parse_mode": "HTML",
                                    "supports_streaming": True,
                                },
                                files={"video": vf},
                            )
            except Exception as notify_err:
                logger.debug("YouTube: не удалось отправить уведомление: %s", notify_err)

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
            import traceback
            logger.error("YouTube: ошибка канала %s: %s\n%s", ch_name, e, traceback.format_exc())

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

        # Проверяем — видео уже скачано?
        dl = item.get("downloaded_file", "")
        if dl and os.path.isfile(dl):
            filepath = dl
            logger.info("YouTube: использую уже скачанный файл %s: %s", video_id, filepath)
        else:
            logger.info("YouTube: обрабатываю одобрение для %s — скачиваю...", video_id)
            downloads_dir = "downloads"
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
        "YouTube монитор v3: запущен (yt-dlp, интервал=%dч, модерация)",
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

    logger.info("YouTube монитор v3: standalone режим")
    videos = await check_for_popular_shorts(config=config)

    if videos:
        logger.info("YouTube: найдено %d шортсов", len(videos))
        for v in videos:
            print(format_video_message(v, v.get("category", "")))
            print("-" * 60)
    else:
        logger.info("YouTube: новых шортсов не найдено")