"""
Монитор X/Twitter аккаунта @DayZ для DayZ News Monitor.

Использует официальный Twitter API v2 (tweepy).
Бесплатный tier: 1500 запросов/месяц — хватит с запасом.

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

from logger import logger


# ═════════════════════════════════════════════════════════════════════════════
#  Константы
# ═════════════════════════════════════════════════════════════════════════════

DAYZ_TWITTER_HANDLE = "DayZ"
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
    return {"posted_ids": [], "last_check": None, "user_id": None}


def _save_state(state: dict) -> None:
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except IOError as e:
        logger.error("Не удалось сохранить twitter_state.json: %s", e)


# ═════════════════════════════════════════════════════════════════════════════
#  Twitter API v2 (tweepy)
# ═════════════════════════════════════════════════════════════════════════════

def _get_client(bearer_token: str):
    """Создаёт tweepy Client. Вынесено в функцию для удобного мока в тестах."""
    import tweepy
    return tweepy.Client(bearer_token=bearer_token)


def _resolve_user_id(client, username: str, state: dict) -> Optional[str]:
    """Получает user_id по username. Кеширует в state."""
    cached = state.get("user_id")
    if cached:
        return cached

    try:
        resp = client.get_user(username=username, user_fields=["id"])
        if resp and resp.data:
            uid = str(resp.data.id)
            state["user_id"] = uid
            logger.info("Twitter API: @%s -> user_id=%s", username, uid)
            return uid
    except Exception as e:
        logger.error("Twitter API: не удалось получить user_id для @%s: %s", username, e)
    return None


async def _fetch_api_tweets(bearer_token: str, state: dict, max_tweets: int = 20) -> list[dict]:
    """
    Получает твиты через Twitter API v2.

    Возвращает список:
      [{"id": "...", "title": "...", "text": "...",
        "url": "...", "images": [...], "date": "..."}]
    """
    try:
        import tweepy
    except ImportError:
        logger.error("tweepy не установлен. Установи: pip install tweepy")
        return []

    loop = asyncio.get_running_loop()

    try:
        client = _get_client(bearer_token)

        # Определяем user_id (с кешированием)
        user_id = await loop.run_in_executor(None, _resolve_user_id, client, DAYZ_TWITTER_HANDLE, state)
        if not user_id:
            logger.error("Twitter API: не удалось получить user_id для @%s", DAYZ_TWITTER_HANDLE)
            return []

        # Запрашиваем твиты
        def _get_tweets():
            return client.get_users_tweets(
                id=user_id,
                max_results=min(max_tweets, 100),
                tweet_fields=["created_at", "text", "attachments"],
                media_fields=["url", "type", "preview_image_url"],
                expansions=["attachments.media_keys"],
                exclude=["replies"],
            )

        resp = await loop.run_in_executor(None, _get_tweets)

        if not resp or not resp.data:
            logger.info("Twitter API: у @%s нет новых твитов или пустой ответ", DAYZ_TWITTER_HANDLE)
            return []

        # Строим lookup-таблицу media_key -> media
        media_lookup = {}
        if resp.includes and "media" in resp.includes:
            for media in resp.includes["media"]:
                media_lookup[media.media_key] = {
                    "url": media.url or "",
                    "type": media.type or "photo",
                    "preview": getattr(media, "preview_image_url", "") or "",
                }

        tweets = []
        for tweet in resp.data:
            tid = str(tweet.id)
            text = tweet.text or ""

            # Извлекаем картинки из attachments
            images = []
            if hasattr(tweet, "attachments") and tweet.attachments:
                for mkey in tweet.attachments.get("media_keys", []):
                    m = media_lookup.get(mkey)
                    if m:
                        img_url = m["url"]
                        if not img_url and m["type"] == "video":
                            img_url = m["preview"]  # превью для видео
                        if img_url:
                            images.append(img_url)

            # Дата
            date_str = ""
            if tweet.created_at:
                if hasattr(tweet.created_at, "isoformat"):
                    date_str = tweet.created_at.astimezone(timezone.utc).isoformat()
                else:
                    date_str = str(tweet.created_at)

            tweets.append({
                "id": tid,
                "title": text[:100],
                "text": text,
                "url": f"https://x.com/{DAYZ_TWITTER_HANDLE}/status/{tid}",
                "images": images[:4],
                "date": date_str,
                "source": f"@{DAYZ_TWITTER_HANDLE}",
            })

        logger.info("Twitter API: получено %d твитов", len(tweets))
        return tweets

    except tweepy.TooManyRequests:
        logger.warning("Twitter API: exceeded rate limit — ждём до следующего интервала")
        return []
    except tweepy.Unauthorized:
        logger.error("Twitter API: неверный Bearer Token — проверь twitter_bearer_token в config.json")
        return []
    except tweepy.Forbidden as e:
        logger.error("Twitter API: доступ запрещён (Free tier может не поддерживать чтение): %s", e)
        return []
    except Exception as e:
        logger.error("Twitter API: ошибка получения твитов: %s", e)
        return []


# ═════════════════════════════════════════════════════════════════════════════
#  Фильтрация
# ═════════════════════════════════════════════════════════════════════════════

_SKIP_PATTERNS = re.compile(r"^(@\w+\s+){2,}")


def _is_relevant(tweet: dict) -> bool:
    """Фильтруем: только оригинальные твиты с контентом."""
    text = tweet.get("title", "") or tweet.get("text", "")

    if _SKIP_PATTERNS.match(text):
        return False

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

    if ai_description:
        parts.append(ai_description)
    else:
        text = tweet.get("text", "") or tweet.get("title", "")
        parts.append(_escape_html(text[:500]))

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
    bearer_token: str = "",
):
    """Основной цикл монитора @DayZ в X/Twitter.

    Использует официальный Twitter API v2 (tweepy).
    Контент идёт через модерацию:
      1. Сохраняется в БД (source_type='twitter')
      2. Отправляется на веб-панель для модерации
      3. Публикуется в Telegram ТОЛЬКО после одобрения на панели
    """
    if not bearer_token:
        logger.error("Twitter Monitor: не указан twitter_bearer_token в config.json — монитор отключён")
        return

    logger.info("Twitter Monitor запущен через Twitter API v2 (интервал: %d сек)", check_interval)

    state = _load_state()

    # При старте — проверяем last_check
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
            logger.info("Проверяем @DayZ через Twitter API v2...")

            tweets = await _fetch_api_tweets(
                bearer_token=bearer_token,
                state=state,
                max_tweets=20,
            )

            posted_ids = set(state.get("posted_ids", []))
            new_count = 0

            if not tweets:
                logger.info("Twitter: нет новых твитов")
            else:
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

                        if not saved_to_db and not web_panel_url:
                            logger.warning(
                                "Твит #%s пропущен: нет БД и веб-панели для модерации",
                                tweet["id"],
                            )

                        posted_ids.add(tweet["id"])
                        new_count += 1
                        await asyncio.sleep(2)

                    except Exception as e:
                        logger.error("Ошибка обработки твита #%s: %s", tweet["id"], e)

                if new_count:
                    logger.info("Twitter: обработано %d новых твитов", new_count)

            # Сохраняем состояние (включая кешированный user_id)
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

async def fetch_twitter_tweets(max_tweets: int = 5, bearer_token: str = "") -> list[dict]:
    """Публичная функция для получения твитов (без побочных эффектов)."""
    state = {"user_id": None}
    tweets = await _fetch_api_tweets(bearer_token=bearer_token, state=state, max_tweets=max_tweets)
    return [t for t in tweets if _is_relevant(t)]