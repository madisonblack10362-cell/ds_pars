"""
Монитор X/Twitter аккаунта @DayZ для DayZ News Monitor.

Парсит твиты через RSS-ленту (Nitter/XCanceller mirror).
Если RSS недоступен — фоллбэк на скрейпинг syndication.twitter.com.

Контент идёт через модерацию:
  1. Сохраняется в БД (source_type='twitter')
  2. Отправляется на веб-панель
  3. Публикуется в Telegram только после одобрения

Хранение состояния:
  twitter_state.json — {"posted_ids": [...], "last_check": "ISO"}
"""

import asyncio
import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Optional

import aiohttp
import feedparser

from logger import logger


# ═════════════════════════════════════════════════════════════════════════════
#  Константы
# ═════════════════════════════════════════════════════════════════════════════

DAYZ_TWITTER_HANDLE = "DayZ"

# RSS-ленты (попробуем по порядку)
RSS_FEED_URLS = [
    f"https://nitter.privacydev.net/{DAYZ_TWITTER_HANDLE}/rss",
    f"https://nitter.poast.org/{DAYZ_TWITTER_HANDLE}/rss",
    f"https://twiiit.com/{DAYZ_TWITTER_HANDLE}/rss",
    f"https://nitter.cz/{DAYZ_TWITTER_HANDLE}/rss",
    f"https://xcancel.com/{DAYZ_TWITTER_HANDLE}/rss",
    f"https://nitter.net/{DAYZ_TWITTER_HANDLE}/rss",
]

# Syndication fallback (embedded JSON в HTML)
SYNDICATION_URL = f"https://syndication.twitter.com/srv/timeline-profile/screen-name/{DAYZ_TWITTER_HANDLE}"

STATE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "twitter_state.json")


# ═════════════════════════════════════════════════════════════════════════════
#  State persistence
# ═════════════════════════════════════════════════════════════════════════════

def _load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning("Не удалось загрузить twitter_state.json: %s", e)
    return {"posted_ids": [], "last_check": None}


def _save_state(state: dict) -> None:
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except IOError as e:
        logger.error("Не удалось сохранить twitter_state.json: %s", e)


# ═════════════════════════════════════════════════════════════════════════════
#  RSS-парсинг (основной метод)
# ═════════════════════════════════════════════════════════════════════════════

async def _fetch_rss_tweets(max_tweets: int = 20) -> list[dict]:
    """
    Пробует RSS-ленты из RSS_FEED_URLS по порядку.
    Возвращает список твитов: [{"id": "...", "title": "...", "text": "...",
    "url": "...", "images": [...], "date": "..."}]
    """
    for rss_url in RSS_FEED_URLS:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    rss_url,
                    timeout=aiohttp.ClientTimeout(total=15),
                    headers={"User-Agent": "Mozilla/5.0 (compatible; DayZMonitor/1.0)"},
                ) as resp:
                    if resp.status != 200:
                        logger.debug("RSS %s вернул %d", rss_url, resp.status)
                        continue
                    raw = await resp.text()

            feed = feedparser.parse(raw)
            if not feed.entries:
                logger.debug("RSS %s: нет записей", rss_url)
                continue

            # Проверка: не whitelisting-сообщение вместо твитов
            first_title = feed.entries[0].get("title", "")
            if "whitelist" in first_title.lower() or "not yet" in first_title.lower():
                logger.warning("RSS %s: whitelisting required, пропускаем", rss_url)
                continue

            # Проверка: есть ли реальные tweet ID в записях
            has_real_tweets = False
            for entry in feed.entries[:max_tweets]:
                entry_id = entry.get("id", "") or entry.get("link", "")
                if re.search(r"/status/\d+", entry_id):
                    has_real_tweets = True
                    break
            if not has_real_tweets:
                logger.warning("RSS %s: нет реальных твитов в записях", rss_url)
                continue

            tweets = []
            for entry in feed.entries[:max_tweets]:
                tweet_id = entry.get("id", "")
                # Извлекаем ID из ссылки или entry_id
                # Формат: https://xcancel.com/DayZ/status/123456789
                m = re.search(r"/status/(\d+)", tweet_id)
                tweet_id = m.group(1) if m else tweet_id

                title = entry.get("title", "").strip()

                # Полный текст из summary или content
                text = ""
                if entry.get("summary"):
                    text = entry["summary"]
                elif entry.get("content"):
                    text = entry["content"][0].get("value", "")

                # Убираем HTML-теги
                text = re.sub(r"<[^>]+>", " ", text).strip()
                # Убираем t.co ссылки-сокращения (сохраним оригинальные если есть)
                text = re.sub(r"https?://t\.co/\S+", "", text).strip()
                text = re.sub(r"\s+", " ", text)

                # Извлекаем картинки из enclosure или content
                images = []
                for enc in entry.get("enclosures", []):
                    href = enc.get("href", "")
                    if href and re.match(r"https?://pbs\.twimg\.com/", href):
                        images.append(href)

                # Попробуем достать картинки из HTML content
                if not images and entry.get("summary"):
                    imgs = re.findall(r'src="(https://pbs\.twimg\.com/[^"]+)"', entry["summary"])
                    images.extend(imgs)

                # Ссылка на твит
                url = entry.get("link", "")
                if not url and tweet_id.isdigit():
                    url = f"https://x.com/{DAYZ_TWITTER_HANDLE}/status/{tweet_id}"

                # Дата
                date_str = ""
                published = entry.get("published", "") or entry.get("updated", "")
                if published:
                    try:
                        dt = datetime.strptime(published, "%a, %d %b %Y %H:%M:%S %z")
                        date_str = dt.astimezone(timezone.utc).isoformat()
                    except (ValueError, TypeError):
                        date_str = published

                if title or text:
                    tweets.append({
                        "id": str(tweet_id),
                        "title": title or text[:100],
                        "text": text or title,
                        "url": url,
                        "images": images[:4],  # Макс 4 картинки
                        "date": date_str,
                        "source": f"@{DAYZ_TWITTER_HANDLE}",
                    })

            if tweets:
                logger.info("RSS: получено %d твитов из %s", len(tweets), rss_url)
                return tweets

        except Exception as e:
            logger.debug("RSS %s ошибка: %s", rss_url, e)
            continue

    logger.warning("Все RSS-ленты недоступны")
    return []


# ═════════════════════════════════════════════════════════════════════════════
#  Syndication fallback (скрейпинг HTML)
# ═════════════════════════════════════════════════════════════════════════════

async def _fetch_syndication_tweets(max_tweets: int = 20) -> list[dict]:
    """
    Fallback: парсит syndication.twitter.com.
    Встроенный JSON с твитами содержится в HTML-ответе.
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                SYNDICATION_URL,
                timeout=aiohttp.ClientTimeout(total=15),
                headers={"User-Agent": "Mozilla/5.0 (compatible; DayZMonitor/1.0)"},
            ) as resp:
                if resp.status != 200:
                    return []
                raw = await resp.text()

        # Ищем встроенный JSON в HTML
        tweets = []
        # Список всех match-групп tweet ID
        tweet_ids = re.findall(r'data-tweet-id="(\d+)"', raw)
        # Tweet text
        tweet_texts = re.findall(r'data-tweet-text="([^"]*)"', raw)
        # Ссылки на изображения
        all_images = re.findall(r'(https://pbs\.twimg\.com/media/[^\s"\'<>]+)', raw)

        for i, tid in enumerate(tweet_ids[:max_tweets]):
            text = tweet_texts[i] if i < len(tweet_texts) else ""
            # Unescape HTML entities
            text = text.replace("&lt;", "<").replace("&gt;", ">")
            text = text.replace("&amp;", "&").replace("&quot;", '"')

            if not text:
                continue

            tweets.append({
                "id": tid,
                "title": text[:100],
                "text": text,
                "url": f"https://x.com/{DAYZ_TWITTER_HANDLE}/status/{tid}",
                "images": [],
                "date": "",
                "source": f"@{DAYZ_TWITTER_HANDLE}",
            })

        if tweets:
            logger.info("Syndication: получено %d твитов", len(tweets))

        return tweets

    except Exception as e:
        logger.warning("Syndication fallback ошибка: %s", e)
        return []


# ═════════════════════════════════════════════════════════════════════════════
#  Фильтрация
# ═════════════════════════════════════════════════════════════════════════════

# Пропускаем твиты с этими словами (реплаи, ретвиты без контента)
_SKIP_PATTERNS = re.compile(
    r"^(@\w+\s+){2,}",  # Начинается с 2+ упоминаний (реплай-цепочка)
)


def _is_relevant(tweet: dict) -> bool:
    """Фильтруем: только оригинальные твиты с контентом."""
    text = tweet.get("title", "") or tweet.get("text", "")

    # Пропускаем реплай-цепочки
    if _SKIP_PATTERNS.match(text):
        return False

    # Пропускаем слишком короткие (меньше 10 символов полезного текста)
    clean = re.sub(r"https?://\S+", "", text).strip()
    if len(clean) < 10 and not tweet.get("images"):
        return False

    return True


# ═════════════════════════════════════════════════════════════════════════════
#  AI-анализ: генерация описания на русском
# ═════════════════════════════════════════════════════════════════════════════

_TWITTER_AI_PROMPT = """Ты — редактор русскоязычного Telegram-канала про DayZ.
Тебе приходит твит от официального аккаунта @DayZ (на английском).

Задача: напиши короткий пост (2-4 предложения) на русском для канала.
Правила:
- Если твит — скриншот/арт/тизер: опиши что на картинке, добавь контекст
- Если твит — текстовая новость: кратко перескажи суть на русском
- НЕ переводи дословно — сделай живое описание
- Если есть картинка — пост должен быть про визуальный контент
- Максимум 3-4 предложения
- Не добавляй хештеги
- Начинай прямо с текста, без приветствий

Твит:
{text}
{images_note}"""


async def _ai_generate_russian_description(tweet: dict, ai_analyzer) -> str:
    """Генерирует описание твита на русском через AI."""
    text = tweet.get("text", "") or tweet.get("title", "")
    num_images = len(tweet.get("images", []))
    images_note = f"\n\nКартинки: {num_images} шт." if num_images else ""

    prompt = _TWITTER_AI_PROMPT.format(
        text=text[:500],
        images_note=images_note,
    )

    try:
        result = await ai_analyzer.chat_completion(prompt)
        if result and result.strip():
            return result.strip()
    except Exception as e:
        logger.error("AI генерация описания твита не удалась: %s", e)

    return ""


# ═════════════════════════════════════════════════════════════════════════════
#  Форматирование поста
# ═════════════════════════════════════════════════════════════════════════════

def _escape_html(text: str) -> str:
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    return text


def format_tweet_message(tweet: dict, ai_description: str = "") -> dict:
    """Форматирует твит для Telegram-поста."""
    parts = []

    # AI-описание на русском
    if ai_description:
        parts.append(ai_description)
    else:
        # Без AI — просто текст твита (эскейпим)
        text = tweet.get("text", "") or tweet.get("title", "")
        parts.append(_escape_html(text[:500]))

    # Ссылка на оригинал
    url = tweet.get("url", "")
    if url:
        parts.append("")
        parts.append(f'🔗 <a href="{url}">Оригинал в X/Twitter</a>')

    return {
        "text": "\n".join(parts),
        "photo_url": tweet["images"][0] if tweet.get("images") else "",
        "tweet_id": tweet["id"],
    }


# ═════════════════════════════════════════════════════════════════════════════
#  Основной цикл
# ═════════════════════════════════════════════════════════════════════════════

async def run_twitter_monitor(
    telegram_bot=None,
    db=None,
    ai_analyzer=None,
    web_panel_url: str = "",
    web_panel_api_key: str = "",
    check_interval: int = 3600,
    ai_analyze: bool = True,
    notify_chat_ids: list | None = None,
    telegram_bot_token: str = "",
):
    """Основной цикл монитора @DayZ в X/Twitter.

    Контент идёт через модерацию:
      1. Сохраняется в БД (source_type='twitter')
      2. Отправляется на веб-панель для модерации
      3. Публикуется в Telegram ТОЛЬКО после одобрения на панели
    """
    logger.info("Twitter Monitor запущен (интервал: %d сек)", check_interval)

    # При старте — проверяем last_check
    state = _load_state()
    last_check = state.get("last_check")
    if last_check:
        try:
            last_ts = datetime.fromisoformat(last_check).timestamp()
            elapsed = time.time() - last_ts
            if elapsed < check_interval:
                remaining = check_interval - elapsed
                logger.info(
                    "Twitter: с последней проверки прошло %.0f мин, интервал %d мин — ждём %.0f мин",
                    elapsed / 60, check_interval / 60, remaining / 60,
                )
                await asyncio.sleep(remaining)
        except (ValueError, TypeError):
            pass

    while True:
        try:
            logger.info("Проверяем @DayZ в X/Twitter...")

            # Основной метод: RSS
            tweets = await _fetch_rss_tweets(max_tweets=20)

            # Fallback: syndication
            if not tweets:
                logger.info("RSS недоступен, пробуем syndication fallback...")
                tweets = await _fetch_syndication_tweets(max_tweets=20)

            # Обновляем posted_ids из состояния
            posted_ids = set(state.get("posted_ids", []))
            new_count = 0

            if not tweets:
                logger.info("Twitter: не удалось получить твиты из любого источника")
            else:
                # Фильтруем
                tweets = [t for t in tweets if _is_relevant(t)]
                logger.info("Twitter: получено %d твитов (после фильтрации)", len(tweets))

                for tweet in tweets:
                    if tweet["id"] in posted_ids:
                        continue

                    try:
                        logger.info("Обрабатываем твит #%s: %s",
                                    tweet["id"], tweet.get("title", "")[:60])

                        ai_desc = None
                        if ai_analyze and ai_analyzer:
                            try:
                                ai_desc = await _ai_generate_russian_description(tweet, ai_analyzer)
                            except Exception as e:
                                logger.error("AI анализ твита #%s не удался: %s", tweet["id"], e)

                        msg = format_tweet_message(tweet, ai_desc or "")

                        # --- Модерация: БД + веб-панель ---
                        saved_to_db = False
                        if db:
                            try:
                                images = tweet.get("images", [])
                                links = [tweet["url"]] if tweet.get("url") else []
                                msg_id = await db.save_message(
                                    external_id=tweet["id"],
                                    source_type="twitter",
                                    source_id="twitter_dayz",
                                    server_name="X/Twitter @DayZ",
                                    text=tweet.get("text", ""),
                                    title=tweet.get("title", ""),
                                    author="@DayZ",
                                    images=images,
                                    links=links,
                                )
                                if msg_id:
                                    news_type = "content"
                                    priority = "medium"
                                    summary = ai_desc or ""
                                    formatted_post = msg.get("text", "")

                                    await db.save_processed(
                                        message_id=msg_id,
                                        news_type=news_type,
                                        priority=priority,
                                        should_publish=False,
                                        summary=summary,
                                        server_name="X/Twitter @DayZ",
                                        formatted_post=formatted_post,
                                    )
                                    saved_to_db = True
                                    logger.info(
                                        "Твит #%d отправлен на модерацию (type=%s, priority=%s)",
                                        msg_id, news_type, priority,
                                    )
                            except Exception as e:
                                logger.error("Ошибка сохранения твита #%s в БД: %s", tweet["id"], e)

                        # Веб-панель
                        if web_panel_url:
                            try:
                                from web_app_integration import send_to_web_panel
                                success = await send_to_web_panel(
                                    news_data={
                                        "sourceId": "twitter",
                                        "externalId": tweet["id"],
                                        "serverName": "X/Twitter @DayZ",
                                        "content": tweet.get("text", ""),
                                        "summary": ai_desc or "",
                                        "formattedPost": msg.get("text", ""),
                                        "newsType": "content",
                                        "priority": "medium",
                                        "images": tweet.get("images", []),
                                    },
                                    web_app_url=web_panel_url,
                                    bot_api_key=web_panel_api_key or None,
                                )
                                if success:
                                    logger.info("Твит #%s отправлен на веб-панель", tweet["id"])
                                    if notify_chat_ids and telegram_bot_token:
                                        try:
                                            from web_app_integration import notify_moderation
                                            await notify_moderation(
                                                title=ai_desc or tweet.get("title", "")[:80],
                                                news_type="content",
                                                priority="medium",
                                                source="X/Twitter @DayZ",
                                                notify_chat_ids=notify_chat_ids,
                                                bot_token=telegram_bot_token,
                                                web_panel_url=web_panel_url,
                                            )
                                        except Exception:
                                            pass
                            except Exception as e:
                                logger.error("Ошибка отправки твита #%s на панель: %s", tweet["id"], e)

                        # Fallback: если нет БД и панели — не публикуем автоматически
                        if not saved_to_db and not web_panel_url:
                            logger.warning(
                                "Твит #%s пропущен: нет БД и веб-панели для модерации",
                                tweet["id"],
                            )

                        # Обновляем состояние
                        posted_ids.add(tweet["id"])
                        new_count += 1

                        # Пауза между обработкой твитов
                        await asyncio.sleep(2)

                    except Exception as e:
                        logger.error("Ошибка обработки твита #%s: %s", tweet["id"], e)

                if new_count:
                    logger.info("Twitter: обработано %d новых твитов", new_count)

            # Обновляем last_check
            state["last_check"] = datetime.now(timezone.utc).isoformat()
            state["posted_ids"] = list(posted_ids)
            _save_state(state)

        except Exception as e:
            logger.error("Twitter Monitor: ошибка цикла: %s", e)

        logger.info("Twitter: следующая проверка через %d мин", check_interval // 60)
        await asyncio.sleep(check_interval)


# ═════════════════════════════════════════════════════════════════════════════
#  Экспорт для ручного запуска / тестов
# ═════════════════════════════════════════════════════════════════════════════

async def fetch_twitter_tweets(max_tweets: int = 5) -> list[dict]:
    """Публичная функция для получения твитов (без побочных эффектов)."""
    tweets = await _fetch_rss_tweets(max_tweets=max_tweets)
    if not tweets:
        tweets = await _fetch_syndication_tweets(max_tweets=max_tweets)
    return [t for t in tweets if _is_relevant(t)]