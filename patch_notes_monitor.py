"""
Patch Notes Monitor для DayZ

Парсит релиз-ноты из двух источников:
  1) Steam News RSS (основной, надёжный) — feedparser
  2) dayz.com devblog (запасной) — через aiohttp

Хранение состояния:
  patchnotes_state.json — {"posted_ids": [...], "last_check": "ISO"}
"""

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Optional

import aiohttp
import feedparser

logger = logging.getLogger("patch_notes_monitor")

# ─── Конфиг ────────────────────────────────────────────────────────────────────
DAYZ_APPID = 221100
STEAM_NEWS_RSS = f"https://store.steampowered.com/feeds/news/app/{DAYZ_APPID}/"
DAYZ_DEVBLOG_URL = "https://dayz.com/news"

# Ключевые слова для фильтрации патчей
PATCH_KEYWORDS = [
    "update", "patch", "hotfix", "maintenance", "fix",
    "server", "version", "stable", "experimental",
    "expansion", "update ", "patch notes", "changelog",
    "release", "1.",
    "обновление", "патч", "исправлен", "стабильн",
]

STRONG_PATCH_KEYWORDS = [
    "update ", "patch ", "hotfix", "patchnote",
    "changelog", "release note",
]

# ─── State persistence ────────────────────────────────────────────────────────

STATE_FILE = os.path.join(os.path.dirname(__file__), "patchnotes_state.json")


def _load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning("Не удалось загрузить patchnotes_state.json: %s", e)
    return {"posted_ids": [], "last_check": None}


def _save_state(state: dict) -> None:
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except IOError as e:
        logger.error("Не удалось сохранить patchnotes_state.json: %s", e)


# ─── Steam News RSS парсинг ───────────────────────────────────────────────────

def _parse_steam_rss_entry(entry: dict) -> Optional[dict]:
    try:
        title = entry.get("title", "").strip()
        link = entry.get("link", "").strip()
        if not title:
            return None

        entry_id = entry.get("id", link)
        if not entry_id:
            entry_id = link

        published_parsed = entry.get("published_parsed")
        date_str = ""
        timestamp = 0

        if published_parsed:
            try:
                from time import mktime
                timestamp = mktime(published_parsed)
                date_str = datetime.fromtimestamp(
                    timestamp, tz=timezone.utc
                ).strftime("%d.%m.%Y %H:%M")
            except Exception:
                date_str = entry.get("published", "")[:16] if entry.get("published") else ""

        summary = entry.get("summary", "")
        content_list = entry.get("content", [])
        if content_list and isinstance(content_list, list):
            full_content = content_list[0].get("value", "")
        else:
            full_content = summary

        clean_text = _strip_html_tags(full_content)
        is_patch = _is_patch_note(title, clean_text)
        image_url = _extract_first_image(full_content)

        return {
            "id": entry_id,
            "title": title,
            "link": link,
            "date": date_str,
            "timestamp": timestamp,
            "summary": _strip_html_tags(summary)[:500],
            "content": clean_text[:3000],
            "image_url": image_url,
            "is_patch": is_patch,
            "source": "steam_rss",
        }

    except Exception as e:
        logger.error("Ошибка парсинга RSS записи: %s", e)
        return None


def _is_patch_note(title: str, content: str) -> bool:
    title_lower = title.lower()
    content_lower = content.lower()[:1000]

    for kw in STRONG_PATCH_KEYWORDS:
        if kw in title_lower:
            return True

    title_matches = sum(1 for kw in PATCH_KEYWORDS if kw in title_lower)
    if title_matches >= 1:
        return True

    content_matches = sum(1 for kw in PATCH_KEYWORDS if kw in content_lower)
    if content_matches >= 2:
        return True

    return False


def _strip_html_tags(html: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", html)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&amp;", "&")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    text = text.replace("&quot;", '"')
    text = text.replace("&#39;", "'")
    text = text.replace("&nbsp;", " ")
    text = re.sub(r"\n\s*\n", "\n", text)
    text = re.sub(r"  +", " ", text)
    return text.strip()


def _extract_first_image(html: str) -> str:
    match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', html)
    return match.group(1) if match else ""


async def fetch_steam_news(max_entries: int = 20) -> list:
    news = []
    try:
        loop = asyncio.get_running_loop()
        feed = await loop.run_in_executor(None, feedparser.parse, STEAM_NEWS_RSS)

        entries = feed.get("entries", [])
        logger.info("Steam RSS: получено %d записей", len(entries))

        for entry in entries[:max_entries]:
            item = _parse_steam_rss_entry(entry)
            if item:
                news.append(item)

    except Exception as e:
        logger.error("Ошибка парсинга Steam News RSS: %s", e)

    return news


# ─── dayz.com Devblog парсинг ────────────────────────────────────────────────

async def fetch_dayz_devblog() -> list:
    news = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                DAYZ_DEVBLOG_URL,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
                allow_redirects=True,
            ) as resp:
                if resp.status != 200:
                    logger.warning("dayz.com вернул статус %d", resp.status)
                    return []

                html = await resp.text()

        article_pattern = re.compile(
            r'<article[^>]*>.*?'
            r'<a[^>]+href="([^"]+)"[^>]*>.*?'
            r'<(?:h2|h3)[^>]*>(.*?)</(?:h2|h3)>.*?'
            r'(?:<time[^>]*datetime="([^"]+)"[^>]*>|<span[^>]*class="[^"]*date[^"]*"[^>]*>(.*?)</span>).*?'
            r'</article>',
            re.DOTALL | re.IGNORECASE,
        )

        for match in article_pattern.finditer(html):
            url = match.group(1)
            title = _strip_html_tags(match.group(2)).strip()
            date_iso = match.group(3) or match.group(4) or ""

            if not title:
                continue

            is_patch = _is_patch_note(title, "")

            news.append({
                "id": url,
                "title": title,
                "link": url if url.startswith("http") else f"https://dayz.com{url}",
                "date": date_iso[:10] if date_iso else "",
                "timestamp": 0,
                "summary": "",
                "content": "",
                "image_url": "",
                "is_patch": is_patch,
                "source": "dayz_com",
            })

    except Exception as e:
        logger.error("Ошибка парсинга dayz.com: %s", e)

    return news


# ─── Основная логика монитора ──────────────────────────────────────────────────

async def check_for_new_patches(include_non_patch: bool = False) -> list:
    state = _load_state()
    posted_ids = set(state.get("posted_ids", []))

    all_news = await fetch_steam_news(max_entries=20)

    dayz_news = await fetch_dayz_devblog()
    existing_ids = {item["id"] for item in all_news}
    for item in dayz_news:
        if item["id"] not in existing_ids:
            all_news.append(item)

    new_patches = []
    for item in all_news:
        if item["id"] in posted_ids:
            continue
        if not item.get("is_patch", False) and not include_non_patch:
            continue
        new_patches.append(item)

    state["last_check"] = datetime.now(timezone.utc).isoformat()
    _save_state(state)

    if new_patches:
        logger.info("Найдено %d новых патчей/обновлений", len(new_patches))
    else:
        logger.info("Новых патчей/обновлений не найдено")

    return new_patches


# ─── Telegram formatting ─────────────────────────────────────────────────────

def format_patch_message(item: dict, ai_summary: Optional[str] = None) -> dict:
    icon = "📋"

    parts = [
        f"{icon} <b>{_escape_html(item['title'])}</b>",
        "",
    ]

    source_label = {
        "steam_rss": "Steam",
        "dayz_com": "dayz.com",
    }.get(item.get("source", ""), "Steam")
    parts.append(f"📢 Источник: {source_label}")

    if item.get("date"):
        parts.append(f"📅 Дата: {item['date']}")

    if ai_summary:
        parts.append("")
        parts.append(ai_summary)
    else:
        summary = item.get("summary", "").strip()
        if summary:
            parts.append("")
            parts.append(_escape_html(summary[:500]))

    if item.get("link"):
        parts.append("")
        parts.append(f'🔗 <a href="{item["link"]}">Читать полностью</a>')

    text = "\n".join(parts)

    return {
        "text": text,
        "photo_url": item.get("image_url", ""),
        "patch_id": item["id"],
    }


def _escape_html(text: str) -> str:
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    return text


# ─── Основной цикл ─────────────────────────────────────────────────────────────

async def run_patch_monitor(
    telegram_bot=None,
    db=None,
    ai_analyzer=None,
    web_panel_url: str = "",
    web_panel_api_key: str = "",
    check_interval: int = 1800,
    ai_analyze: bool = True,
):
    """Основной цикл монитора патчноутов.

    Контент идёт через модерацию:
      1. Сохраняется в БД как сообщение (source_type='patchnotes')
      2. Отправляется на веб-панель для модерации
      3. Публикуется в Telegram ТОЛЬКО после одобрения на панели
    """
    logger.info("Patch Notes Monitor запущен (интервал: %d сек)", check_interval)

    while True:
        try:
            logger.info("Проверяем патчноуты DayZ...")
            new_patches = await check_for_new_patches(include_non_patch=False)

            for item in new_patches:
                try:
                    logger.info("Обрабатываем: %s (ID: %s)", item["title"], item["id"])

                    ai_summary = None
                    if ai_analyze and ai_analyzer:
                        try:
                            ai_summary = await ai_analyzer.analyze_patch_notes(item)
                        except Exception as e:
                            logger.error("AI анализ патча %s не удался: %s", item["id"], e)
                    elif ai_analyze:
                        # Fallback: standalone-анализ без экземпляра анализатора
                        try:
                            from ai_analyzer import analyze_patch_notes
                            ai_summary = await analyze_patch_notes(item)
                        except Exception as e:
                            logger.error("AI анализ патча %s не удался: %s", item["id"], e)

                    msg = format_patch_message(item, ai_summary)

                    # --- Модерация: сохраняем в БД + отправляем на веб-панель ---
                    saved_to_db = False
                    if db:
                        try:
                            images = [item.get("image_url")] if item.get("image_url") else []
                            links = [item.get("link")] if item.get("link") else []
                            content_text = item.get("content", "") or item.get("summary", "") or item.get("title", "")
                            msg_id = await db.save_message(
                                external_id=item["id"],
                                source_type="patchnotes",
                                source_id=f"steam_news_{item.get('source', 'rss')}",
                                server_name=item.get("source", "Steam News"),
                                text=content_text,
                                title=item.get("title", ""),
                                images=images,
                                links=links,
                            )
                            if msg_id:
                                news_type = "update"
                                priority = "high"
                                summary = ai_summary or ""
                                formatted_post = msg.get("text", "")

                                await db.save_processed(
                                    message_id=msg_id,
                                    news_type=news_type,
                                    priority=priority,
                                    should_publish=False,
                                    summary=summary,
                                    server_name=item.get("source", "Steam News"),
                                    formatted_post=formatted_post,
                                )
                                saved_to_db = True
                                logger.info(
                                    "Патч '%s' #%d отправлен на модерацию (type=%s, priority=%s)",
                                    item["title"], msg_id, news_type, priority,
                                )
                        except Exception as e:
                            logger.error("Ошибка сохранения патча %s в БД: %s", item["id"], e)

                    # Отправляем на веб-панель для модерации
                    if web_panel_url:
                        try:
                            from web_app_integration import send_to_web_panel
                            success = await send_to_web_panel(
                                news_data={
                                    "externalId": item["id"],
                                    "serverName": item.get("source", "Steam News"),
                                    "content": item.get("content", "") or item.get("summary", "") or item.get("title", ""),
                                    "summary": ai_summary or "",
                                    "formattedPost": msg.get("text", ""),
                                    "newsType": "update",
                                    "priority": "high",
                                    "images": [item.get("image_url")] if item.get("image_url") else [],
                                },
                                web_app_url=web_panel_url,
                                bot_api_key=web_panel_api_key or None,
                            )
                            if success:
                                logger.info("Патч '%s' отправлен на веб-панель", item["title"])
                            else:
                                logger.error("Веб-панель: не удалось отправить патч '%s'", item["title"])
                        except ImportError:
                            logger.warning("web_app_integration не найден — модерация через панель недоступна")
                        except Exception as e:
                            logger.error("Ошибка отправки патча на веб-панель: %s", e)
                    elif not saved_to_db:
                        # Нет БД и нет веб-панели — fallback: прямой отправ (старое поведение)
                        if telegram_bot:
                            await telegram_bot.send_patch_post(msg)
                            logger.info("Патч '%s' опубликован в Telegram (без модерации — нет БД/панели)", item["title"])

                    # Отмечаем как отправленный в state
                    state = _load_state()
                    if item["id"] not in state.get("posted_ids", []):
                        state["posted_ids"].append(item["id"])
                        _save_state(state)

                except Exception as e:
                    logger.error("Ошибка обработки патча %s: %s", item.get("id", "unknown"), e)

        except Exception as e:
            logger.error("Ошибка в основном цикле Patch Notes монитора: %s", e)

        logger.info("Следующая проверка через %d секунд...", check_interval)
        await asyncio.sleep(check_interval)


# ─── Тестовый запуск ───────────────────────────────────────────────────────────

async def test_fetch():
    print("=" * 60)
    print("📋 Тест Patch Notes Monitor")
    print("=" * 60)

    print("\n📡 Получаем новости из Steam News RSS...")
    news = await fetch_steam_news(max_entries=10)

    if not news:
        print("❌ Не удалось получить новости.")
        return

    print(f"✅ Получено {len(news)} записей\n")

    patches = [item for item in news if item.get("is_patch")]
    non_patches = [item for item in news if not item.get("is_patch")]

    print(f"📋 Патчи/обновления ({len(patches)}):")
    for i, item in enumerate(patches, 1):
        print(f"  #{i}: {item['title']}")
        print(f"      Дата: {item['date']} | Источник: {item['source']}")

    if non_patches:
        print(f"\n📰 Обычные новости ({len(non_patches)}):")
        for i, item in enumerate(non_patches[:3], 1):
            print(f"  #{i}: {item['title']}")

    print("\n✅ Тест завершён!")


if __name__ == "__main__":
    asyncio.run(test_fetch())
