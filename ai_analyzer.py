"""
Модуль AI-анализа новостей проекта DayZ News Monitor.
Использует OpenAI API для определения типа новости, приоритета,
необходимости публикации и генерации краткого резюме.
"""

import asyncio
import json
import re
from typing import Optional

import aiohttp

from logger import logger


# Системный промпт для LLM — задаёт контекст и правила классификации
SYSTEM_PROMPT = """Ты — аналитик и редактор новостей DayZ-серверов. Анализируй сообщение и подготовь пост для Telegram.

ОПРЕДЕЛЕНИЕ СЕРВЕРА (САМОЕ ВАЖНОЕ):
1. В запросе будет указан автор новости в формате [АВТОР: Имя]. Это имя автора ВСЕГДА является названием сервера. Используй его как server_name.
2. НЕ придумывай название сервера из текста — используй то что дано в [АВТОР: ...].
3. server_name — чистое имя из поля [АВТОР] без лишних слов.
4. Если в тексте есть ссылка на сервер (Discord invite, сайт сервера, IP) — это server_link.
5. server_link — URL сервера если найден в тексте, иначе пустая строка "".

ПРАВИЛА КЛАССИФИКАЦИИ:

wipe — ТОЛЬКО если сообщение прямо говорит о вайпе/сбросе (full wipe, partial wipe, сброс базы, вайп персонажей).
update — если есть изменения: новое оружие, новые постройки, обновление модов, исправление багов, изменение хп, баланс. БОЛЬШИНСТВО новостей — это update.
server_open — открытие нового сервера.
event — турнир, ивент, конкурс.
maintenance — технические работы, перезапуск.

Если сообщение говорит и о вайпе, и об обновлении — это wipe (вайп важнее).

ПРИОРИТЕТЫ:
- high: wipe, server_open, new_season, important_announcement
- medium: update, event, maintenance, balance_change, mod_update, bugfix, content_add
- low: chat, meme, poll, congratulations, recruitment, social_advertisement, other

ФОРМАТ ПОСТА: Telegram HTML (ParseMode.HTML).
ВАЖНО: Telegram НЕ поддерживает цветной текст. Используй ТОЛЬКО: <b>, <i>, <code>, <pre>, <blockquote>, <a>, <s>.
Для визуального разделения заголовков и тела: <b> для заголовков, <blockquote> для деталей.

СТРУКТУРА ПОСТА (строго по порядку):

1. ЗАГОЛОВОК (всегда первый элемент, НЕ в blockquote):
   <a href="ССЫЛКА">🎮 ИмяСервера</a>  <b>⚠️ ВАЙП</b>
   (если нет ссылки — просто 🎮 ИмяСервера)

2. ОСНОВНОЙ ТЕКСТ (весь в одном <blockquote>):
   <blockquote>
   Краткое описание что произошло, 1-3 предложения.
   Детали через переносы строк:
   • пункт 1
   • пункт 2
   </blockquote>

3. В конце (вне blockquote): IP в <code>коде</code> + хештеги

ПРАВИЛА КРАСОТЫХ ПОСТОВ:
1. НЕ ПРИДУМЫВАЙ текст. ПЕРЕПИСЫВАЙ исходный текст красиво, но СОХРАНЯЙ ВСЕ ФАКТЫ.
2. НЕ ДОБАВЛЯЙ слова типа "наш", "запланирован" если их нет в оригинале.
3. СОХРАНЯЙ все даты, времена, IP-адреса, названия серверов, ссылки.
4. Заголовок сервера + тип новости — СТРОГО ВНЕ blockquote.
5. Весь основной текст и детали — ВНУТРИ одного blockquote.
6. <code>код</code> — для названий предметов, оружия, карт, IP-адресов.
7. <b>жирный</b> — для дат и ключевых слов внутри blockquote.
8. <a href="URL">текст ссылки</a> — ВСЕ ссылки в тексте ДОЛЖНЫ быть кликабельными. НЕ оставляй голые URL (https://...). Любой URL в тексте должен быть обёрнут: <a href="URL">название</a> или <a href="URL">URL</a>. Это ОБЯЗАТЕЛЬНО.
9. НЕ делай несколько отдельных blockquote — собирай всё в ОДИН blockquote.
10. Если в оригинальном тексте есть URL без обёртки (просто https://...) — ОБЯЗАТЕЛЬНО оберни его в <a href="URL">...</a>.

ПРИМЕР (сервер "Гроза"):
Исходная: "Всем привет! На Грозе завтра вайп. Добавлено новое оружие М4. Изменен спавн. IP 185.189.255.190:2705 discord.gg/groza"

JSON:
{
  "news_type": "wipe",
  "priority": "high",
  "should_publish": true,
  "server_name": "Гроза",
  "server_link": "https://discord.gg/groza",
  "formatted_post": "<a href=\"https://discord.gg/groza\">🎮 Гроза</a> <b>⚠️ ВАЙП</b>\n\n<blockquote>На сервере Гроза завтра произойдет вайп.\n\n<b>➕ Добавлено:</b>\n• Новое оружие <code>М4</code>\n\n<b>🔧 Изменено:</b>\n• Обновлён спавн</blockquote>\n\n<code>185.189.255.190:2705</code>\n\n#dayz #вайп"
}

ПРИМЕР БЕЗ ССЫЛКИ (сервер "Зона"):
Исходная: "На Зоне ивент начинается в 20:00 МСК, приз тортушка"

JSON:
{
  "news_type": "event",
  "priority": "medium",
  "should_publish": true,
  "server_name": "Зона",
  "server_link": "",
  "formatted_post": "🎮 Зона <b>🎉 СОБЫТИЕ</b>\n\n<blockquote>На сервере Зона начинается ивент в <b>20:00 МСК</b>.\nПриз — тортушка.</blockquote>\n\n#dayz #событие"
}

НЕПРАВИЛЬНЫЕ ПРИМЕРЫ:
❌ Без заголовка сервера — всегда начинай с 🎮 ИмяСервера
❌ Не придумывай факты, не меняй даты
❌ wipe для каждого поста — большинство news это update
❌ Много отдельных blockquote — всё тело в ОДИН blockquote
❌ Голые URL без <a href=""> — ВСЕ ссылки должны быть кликабельными

Формат ответа — ТОЛЬКО JSON без markdown:
{"news_type": "...", "priority": "...", "should_publish": true/false, "server_name": "...", "server_link": "...", "formatted_post": "HTML"}
"""



class AIAnalyzer:
    """Анализирует новости с помощью LLM API."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o-mini",
        max_retries: int = 3,
        timeout: int = 30,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_retries = max_retries
        self.timeout = aiohttp.ClientTimeout(total=timeout)

    async def analyze(self, text: str, author: str = "") -> Optional[dict]:
        """
        Анализирует текст новости через LLM API.

        Args:
            text: Текст новости для анализа.
            author: Имя автора поста (это и есть название сервера).

        Returns:
            Словарь с полями news_type, priority, should_publish, summary
            или None при ошибке.
        """
        if not text or len(text.strip()) < 15:
            return {
                "news_type": "other",
                "priority": "low",
                "should_publish": False,
                "summary": "Текст слишком короткий для анализа",
            }

        # Обрезаем текст до разумной длины (примерно 3000 символов)
        truncated = text[:3000] if len(text) > 3000 else text

        for attempt in range(1, self.max_retries + 1):
            try:
                result = await self._call_api(truncated, author)
                if result:
                    return self._validate_result(result)
                # result is None — LLM вернул что-то нечитаемое, пробуем ещё
                logger.warning("Попытка %d/%d: LLM вернул пустой результат", attempt, self.max_retries)
            except Exception as exc:
                logger.warning(
                    "Попытка %d/%d анализа LLM не удалась: %s",
                    attempt, self.max_retries,
                    exc,
                )
            if attempt < self.max_retries:
                await asyncio.sleep(2 ** attempt)

        logger.error("Не удалось проанализировать новость через LLM после %d попыток", self.max_retries)
        return None

    async def _call_api(self, text: str, author: str = "") -> Optional[dict]:
        """Выполняет запрос к OpenAI-совместимому API."""
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Проанализируй новость:{f'\n[АВТОР: {author}]' if author else ''}\n\n{text}"},
            ],
            "temperature": 0.3,
            "max_tokens": 2048,
        }

        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status != 200:
                    body = await response.text()
                    logger.error(
                        "LLM API вернул статус %d: %s", response.status, body[:500]
                    )
                    return None

                data = await response.json()
                content = data["choices"][0]["message"]["content"]
                parsed = self._parse_llm_json(content)
                if parsed is None:
                    logger.warning("Не удалось распарсить JSON от LLM: %s", content[:300])
                return parsed

    @staticmethod
    def _parse_llm_json(raw: str) -> Optional[dict]:
        """Парсит JSON от LLM с несколькими стратегиями восстановления."""
        text = raw.strip()

        # 1. Вырезаем markdown-обёртки
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:])
            if text.rstrip().endswith("```"):
                text = text.rstrip()[:-3]
            text = text.strip()

        # 2. Ищем JSON-объект {...} в тексте
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            text = match.group(0)

        # 3. Пробуем парсить напрямую
        try:
            return json.loads(text, strict=False)
        except (json.JSONDecodeError, ValueError):
            pass

        # 4. Починка: убираем trailing commas перед } или ]
        text = re.sub(r",\s*([\]}])", r"\1", text)

        # 5. Починка: убираем переносы строк внутри строк
        text = re.sub(r'(?<=":)\n(?=\s*")', " ", text)
        text = re.sub(r'(?<=:)\n(?=\s*")', " ", text)

        try:
            return json.loads(text, strict=False)
        except (json.JSONDecodeError, ValueError):
            pass

        # 6. Агрессивная починка: убираем все control chars
        text = re.sub(r"[\x00-\x1f]", " ", text)
        text = re.sub(r"\s{2,}", " ", text)

        try:
            return json.loads(text, strict=False)
        except (json.JSONDecodeError, ValueError):
            pass

        # 7. Фоллбэк: если LLM вернул текст вместо JSON — вытаскиваем данные regex-ом
        return AIAnalyzer._extract_from_text(raw)

    @staticmethod
    def _extract_from_text(raw: str) -> Optional[dict]:
        """
        Фоллбэк: когда LLM возвращает свободный текст вместо JSON,
        вытаскиваем данные через regex-паттерны.
        """
        text = raw.strip()

        # Паттерны для извлечения
        type_patterns = [
            r"тип новости[:\s]+(\w+)",
            r"news_type[:\s]+(\w+)",
            r"тип[:\s]+(\w+)",
        ]
        prio_patterns = [
            r"приоритет[:\s]+(\w+)",
            r"priority[:\s]+(\w+)",
        ]
        publish_patterns = [
            r"(?:нужно|должно|should)\s+(?:публиковать|быть опубликовано|publish)[:\s]*(да|нет|true|false|yes|no)",
        ]
        server_patterns = [
            r"сервер[:\s]+([^\n,]{2,50})",
            r"server_name[:\s]+\"([^\"]+)\"",
        ]

        news_type = "other"
        for p in type_patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                val = m.group(1).lower()
                type_map = {
                    "вайп": "wipe", "wipe": "wipe",
                    "обновление": "update", "update": "update",
                    "ивент": "event", "event": "event",
                    "тех": "maintenance", "техработы": "maintenance", "maintenance": "maintenance",
                    "открытие": "server_open", "server_open": "server_open",
                    "сезон": "new_season", "new_season": "new_season",
                }
                news_type = type_map.get(val, val)
                break

        priority = "medium"
        for p in prio_patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                val = m.group(1).lower()
                if val in ("high", "высокий"):
                    priority = "high"
                elif val in ("medium", "средний"):
                    priority = "medium"
                else:
                    priority = "low"
                break

        should_publish = True
        for p in publish_patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                val = m.group(1).lower()
                should_publish = val in ("да", "true", "yes")
                break

        server_name = ""
        for p in server_patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                server_name = m.group(1).strip()
                break

        server_link = ""
        link_match = re.search(r'"server_link"[:\s]*"([^"]*)"', text)
        if link_match:
            server_link = link_match.group(1).strip()

        # Ищем HTML-пост — весь текст после <b>...</b> или <a>
        formatted_post = ""
        html_match = re.search(r"(<[ab][^>]*>[^<]+</[ab]>.*?)(?=#\w|$)", text, re.DOTALL | re.IGNORECASE)
        if not html_match:
            html_match = re.search(r"(<b>[^<]+</b>.*?)(?=#\w|$)", text, re.DOTALL | re.IGNORECASE)
        if html_match:
            formatted_post = html_match.group(1).strip()

        # Если не нашли HTML — ищем JSON-подобный фрагмент с formatted_post
        if not formatted_post:
            fp_match = re.search(r'"formatted_post"[:\s]*"(.+?)"', text, re.DOTALL)
            if fp_match:
                formatted_post = fp_match.group(1).strip()
                formatted_post = formatted_post.replace('\\n', '\n').replace('\\"', '"')

        logger.info("LLM фоллбэк: извлечено — type=%s, priority=%s, publish=%s, server=%s",
                    news_type, priority, should_publish, server_name)

        return {
            "news_type": news_type,
            "priority": priority,
            "should_publish": should_publish,
            "server_name": server_name[:200],
            "server_link": server_link[:500],
            "formatted_post": formatted_post[:2000],
            "summary": formatted_post[:500] if formatted_post else "",
        }

    @staticmethod
    def _validate_result(result: dict) -> dict:
        """Проверяет и нормализует результат анализа."""
        news_type = result.get("news_type", "other")
        priority = result.get("priority", "low")
        should_publish = bool(result.get("should_publish", False))
        summary = result.get("summary", "")

        # Нормализация приоритета
        if priority not in ("high", "medium", "low"):
            priority = "low"

        # Не переопределяем should_publish — AI уже решил в промпте
        # (раньше здесь было принудительное should_publish=False для low priority,
        # что ломало одобренные новости)

        # Извлекаем server_name, server_link и formatted_post
        server_name = result.get("server_name", "") or ""
        server_link = result.get("server_link", "") or ""
        formatted_post = result.get("formatted_post", "") or ""
        summary = result.get("summary", "") or ""

        # Если есть formatted_post — используем его как summary
        if formatted_post and not summary:
            summary = formatted_post

        return {
            "news_type": news_type,
            "priority": priority,
            "should_publish": should_publish,
            "server_name": server_name[:200],
            "server_link": server_link[:500],
            "formatted_post": formatted_post[:2000],
            "summary": summary[:500],
        }

    async def check_similarity(self, text1: str, text2: str) -> dict | None:
        """
        Использует LLM для проверки смыслового сходства двух текстов.
        Возвращает словарь {"is_duplicate": bool, "similarity_score": float, "reason": str}
        или None при ошибке.
        """
        truncated1 = text1[:1500] if len(text1) > 1500 else text1
        truncated2 = text2[:1500] if len(text2) > 1500 else text2

        prompt = (
            "Сравни две новости DayZ-сервера и определи, являются ли они дубликатами "
            "(одна и та же новость, опубликованная в разных источниках).\n\n"
            f"Новость 1:\n{truncated1}\n\n"
            f"Новость 2:\n{truncated2}\n\n"
            'Ответь ТОЛЬКО JSON: {"is_duplicate": true/false, "similarity_score": 0.0-1.0, '
            '"reason": "краткое объяснение"}'
        )

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "Ты — эксперт по сравнению текстов. Отвечай только JSON."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 200,
        }

        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(url, headers=headers, json=payload) as response:
                    if response.status != 200:
                        return None
                    data = await response.json()
                    content = data["choices"][0]["message"]["content"]
                    return json.loads(content)
        except Exception as exc:
            logger.warning("Ошибка при проверке сходства через LLM: %s", exc)
            return None

    # ─── Steam Workshop Mod — AI описание ────────────────────────────────────

    async def analyze_workshop_mod(self, mod: dict) -> Optional[str]:
        """
        AI-анализ мода Steam Workshop для описания на русском.

        Args:
            mod: Словарь с данными о моде:
                - title, description, tags, subscriptions, author

        Returns:
            AI-описание мода на русском или None при ошибке
        """
        try:
            title = mod.get("title", "Без названия")
            description = mod.get("description", "")
            tags = mod.get("tags", [])
            subs = mod.get("subscriptions", 0)

            if len(description) > 2000:
                description = description[:2000]

            tags_str = ", ".join(str(t) for t in tags[:10]) if tags else "нет тегов"

            user_prompt = (
                f"Название мода: {title}\n"
                f"Описание автора: {description}\n"
                f"Теги: {tags_str}\n"
                f"Подписчики: {subs:,}\n\n"
                f"Напиши краткое описание этого мода для Telegram-канала."
            )

            url = f"{self.base_url}/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": WORKSHOP_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.7,
                "max_tokens": 500,
            }

            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(url, headers=headers, json=payload) as response:
                    if response.status != 200:
                        logger.error("LLM API (Workshop) вернул статус %d", response.status)
                        return None
                    data = await response.json()
                    return data["choices"][0]["message"]["content"].strip()

        except Exception as exc:
            logger.error("Ошибка AI анализа мода: %s", exc)
            return None

    # ─── Patch Notes — AI резюме ──────────────────────────────────────────────

    async def analyze_patch_notes(self, item: dict) -> Optional[str]:
        """
        AI-анализ патчноута для резюме на русском.

        Args:
            item: Словарь с данными о патче:
                - title, content, summary, source

        Returns:
            AI-резюме патча на русском или None при ошибке
        """
        try:
            title = item.get("title", "")
            content = item.get("content", "")
            summary = item.get("summary", "")

            text = content if content else summary
            if not text:
                logger.warning("Нет текста для AI анализа патча '%s'", title)
                return None

            if len(text) > 3000:
                text = text[:3000]

            user_prompt = (
                f"Заголовок: {title}\n\n"
                f"Релиз-ноты:\n{text}\n\n"
                f"Сделай краткое резюме ключевых изменений для Telegram."
            )

            url = f"{self.base_url}/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": PATCHNOTES_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.5,
                "max_tokens": 1000,
            }

            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(url, headers=headers, json=payload) as response:
                    if response.status != 200:
                        logger.error("LLM API (PatchNotes) вернул статус %d", response.status)
                        return None
                    data = await response.json()
                    return data["choices"][0]["message"]["content"].strip()

        except Exception as exc:
            logger.error("Ошибка AI анализа патча: %s", exc)
            return None

    # ─── YouTube Video — AI пересказ + Telegram пост ─────────────────────────

    async def analyze_youtube_video(self, video: dict) -> Optional[dict]:
        """
        AI-пересказ YouTube видео + полноценный Telegram-пост.

        На основе названия, описания, канала и метаданных видео генерирует:
        - summary: краткий пересказ на русском (2-3 предложения)
        - formatted_post: готовый HTML-пост для Telegram
        - news_type: категория контента
        - priority: приоритет

        Args:
            video: Словарь с данными видео:
                - title, description, channel_title, duration, views, likes,
                  thumbnail, url, video_id, category

        Returns:
            Словарь с полями summary, formatted_post, news_type, priority
            или None при ошибке.
        """
        try:
            title = video.get("title", "Без названия")
            description = (video.get("description", "") or "")[:1500]
            channel = video.get("channel_title", "YouTube")
            duration = video.get("duration", 0) or 0
            views = video.get("views", 0) or 0
            url = video.get("url", "")
            category = video.get("category", "other")

            # Форматируем длительность
            dur_str = ""
            if duration and duration > 0:
                m, s = divmod(int(duration), 60)
                dur_str = f"{m}:{s:02d}"

            # Форматируем просмотры
            views_str = ""
            if views:
                if views >= 1_000_000:
                    views_str = f"{views / 1_000_000:.1f}M"
                elif views >= 1_000:
                    views_str = f"{views / 1_000:.1f}K"
                else:
                    views_str = str(views)

            user_prompt = (
                f"Название видео: {title}\n"
                f"Канал: {channel}\n"
                f"Длительность: {dur_str}\n"
                f"Просмотры: {views_str}\n"
                f"Категория: {category}\n"
            )
            if description and len(description.strip()) > 20:
                user_prompt += f"\nОписание:\n{description}"
            else:
                # Явно говорим LLM что описания нет — запрещаем галлюцинации
                user_prompt += "\nОПИСАНИЕ ОТСУТСТВУЕТ. НЕ придумывай содержание видео. Используй только название."

            url_to_post = f"{self.base_url}/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": YOUTUBE_VIDEO_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.5,
                "max_tokens": 1500,
            }

            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(url_to_post, headers=headers, json=payload) as response:
                    if response.status != 200:
                        body = await response.text()
                        logger.error("LLM API (YouTube) вернул статус %d: %s", response.status, body[:500])
                        return None
                    data = await response.json()
                    content = data["choices"][0]["message"]["content"]
                    parsed = self._parse_llm_json(content)
                    if parsed is None:
                        logger.warning("Не удалось распарсить JSON от LLM (YouTube): %s", content[:300])
                        return None

                    # Пост-обработка: вырезаем YouTube ссылки из ответа
                    for key in ("formatted_post", "summary"):
                        if parsed.get(key):
                            parsed[key] = re.sub(
                                r'https?://(?:www\.)?(?:youtube\.com/(?:watch\?v=|shorts/|embed/)|youtu\.be/)\S+',
                                '', parsed[key]
                            ).strip()
                            # Убираем висящие пустые строки после вырезания ссылки
                            parsed[key] = re.sub(r'\n{3,}', '\n\n', parsed[key]).strip()

                    return parsed

        except Exception as exc:
            logger.error("Ошибка AI анализа YouTube видео: %s", exc)
            return None


# ─── Промпты для новых мониторов ──────────────────────────────────────────────

YOUTUBE_VIDEO_SYSTEM_PROMPT = """Ты — креативный редактор Telegram-канала про DayZ. Ты делаешь ЗАЦЕПЛЯЮЩИЕ посты к YouTube Shorts — видео уже прикреплено к посту, текст должен заставить человека ВОТКНУТЬСЯ И ПРОСМОТРЕТЬ видео.

КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО:
1. Любые ссылки на YouTube (https://youtube.com, https://youtu.be, youtube.com/watch) — НИКОГДА, НИ В КОЕМ СЛУЧАЕ.
2. Блок «Основное» или «Ключевые моменты» с буллетами — ЭТО МУСОР, НЕ ДЕЛАЙ ТАК.
3. Фразы «Автор играет в...», «На видео показано...», «В этом ролике...» — СКУЧНО, ЗАПРЕЩЕНО.
4. Пересказ названия другими словами — ПУСТАЯ ТРАТА МЕСТА.
5. Придумывать сцены, моменты, механики которых нет в названии/описании.

ЧТО ДЕЛАТЬ:
1. Заголовок — кликбейтное переформулирование названия (короткое, дерзкое, с хуком).
2. Если из названия/описания понятен конкретный контент (PVP-момент, лут, вайп, баг и т.д.) — напиши 1-2 предложения которые ДОТАГИВАЮТ зрителя, создают интригу или эмоцию.
3. Если название ничего конкретного не говорит — НЕ выдумывай. Просто заголовок + хэштеги.
4. Хэштеги из названия (убери решётку, добавь в строку через пробел).
5. Метаданные: канал курсивом + ⏱ длительность + 👁 просмотры.

ФОРМАТ ПОСТА (Telegram HTML):

<b>🎮 ЗАЦЕПЛЯЮЩИЙ ЗАГОЛОВОК</b> #хэштег1 #хэштег2

<blockquote>1-2 предложения с интригой/эмоцией/контекстом. Если сказать нечего — БЕЗ blockquote.</blockquote>

<i>Имя канала</i>
⏱ 0:59  👁 16.1K

ПРАВИЛА ФОРМАТИРОВАНИЯ:
- НЕ ставь «Основное:» или заголовки внутри blockquote
- НЕ делай списки с буллетами в blockquote — только связный текст
- Если нечего сказать в blockquote — НЕ добавляй blockquote вообще
- <code>код</code> — для названий оружия, серверов, локаций из названия
- Хэштеги — только из названия видео, без решётки

ПРИМЕРЫ:

Входные данные: Название "ЗАРАШИЛ ПОД ШУМОК ВЫЖИВАЛЬЩИКОВ | DAYZ GROZA", Просмотров 2.7K, Канал "Groza"
{
  "summary": "Подрыв выживальщиков под шумок на сервере Groza.",
  "formatted_post": "<b>🎮 Заразил под шумок всю базу выживальщиков</b> #pvp #dayz #groza\n\n<blockquote>Несколько выживальщиков даже не поняли, что произошло 💀</blockquote>\n\n<i>Groza</i>\n⏱ 1:29  👁 2.7K\n",
  "news_type": "pvp",
  "priority": "medium"
}

Входные данные: Название "Их было слишком много | DAYZ PODPIVAS", Просмотров 16.1K, Описание отсутствует
{
  "summary": "Масштабный момент на DayZ Podpivas.",
  "formatted_post": "<b>🎮 Их было слишком много</b> #dayz #podpivas\n\n<i>Podpivas</i>\n⏱ 0:59  👁 16.1K\n",
  "news_type": "pvp",
  "priority": "medium"
}

Входные данные: Название "Как найти M4 в DayZ 1.25 | Гайд", Описание "В этом видео я показываю лучшие спавны M4 на карте Чернорусь"
{
  "summary": "Гайд по спавнам M4 на Черноруси в DayZ 1.25.",
  "formatted_post": "<b>🎮 Лучшие спавны <code>M4</code> на Черноруси</b> #guide #dayz\n\n<blockquote>Все точки где спавнится <code>M4</code> — от военных баз до скрытых локаций</blockquote>\n\n<i>DayZ Guides</i>\n⏱ 4:35  👁 12.3K\n",
  "news_type": "guide",
  "priority": "medium"
}

ПЛОХОЙ ПРИМЕР (НЕ ДЕЛАЙ ТАК):
❌ <b>🎮 Их было слишком много | DAYZ PODPIVAS</b> #pvp #action\n\n<blockquote>Автор играет в DAYZ на сайте Podpivas.\n\nОсновное:\n• Игра на сайте Podpivas</blockquote>\n\n<i>Дмитрий</i>\n⏱ 0:59  👁 16.1K

ЭТО МУСОР. Не пиши так.

КАТЕГОРИЯ (news_type):
- guide — гайд/обзор/инструкция
- pvp — PvP/рейд/бой
- weapons — оружие
- updates — обновление/патч
- events — ивент/турнир
- bugs — баг/эксплойт
- memes — мем/прикол
- secrets — секрет/пасхалка
- base — строительство базы
- vehicles — транспорт
- other — всё остальное

ПРИОРИТЕТ:
- high: официальное обновление, важный баг/эксплойт
- medium: гайд, PvP, оружие, транспорт
- low: мем, прикол, обычное видео

Формат ответа — ТОЛЬКО JSON без markdown:
{"summary": "...", "formatted_post": "HTML", "news_type": "...", "priority": "..."}
"""

WORKSHOP_SYSTEM_PROMPT = """Ты — эксперт по модам DayZ. Создай краткое, увлекательное описание мода для Telegram-канала на русском языке.

Правила:
- Пиши на русском языке
- Максимум 3-4 предложения (150-250 символов)
- Опиши что делает мод, его главную фичу
- Упомяни чем полезен для игроков
- НЕ выдумывай функции, которых нет в описании
- НЕ придумывай конкретные механики если они не описаны
- Используй emoji по смыслу (1-2 emoji)
- Если описание мода слишком короткое или непонятное — просто перескажи что есть
- Формат: короткий абзац, без заголовков"""

PATCHNOTES_SYSTEM_PROMPT = """Ты — гейм-журналист, специализирующийся на DayZ. Создай краткое резюме патчноута для Telegram-канала на русском языке.

Правила:
- Пиши на русском языке
- Структура: краткое вступление + список ключевых изменений
- Форматируй через bullet points (•)
- Максимум 5-7 самых важных изменений — не пересказывай всё
- Группируй похожие изменения (все фиксы оружия — в один пункт)
- НЕ выдумывай изменения, которых нет в релиз-нотах
- Если текст слишком короткий — просто перескажи что есть
- Используй emoji по категориям:
  🔫 — оружие, 🏗 — строительство, 🧟 — зомби/инфекция
  🚗 — транспорт, 🎨 — визуал, 🐛 — фиксы, ⚙️ — техническое
- В конце — короткий вывод (1 предложение)
- Общий объём: 200-400 символов"""


# ─── Standalone функции (для использования без AIAnalyzer instance) ──────────

# Глобальный instance для standalone вызовов
_analyzer_instance: Optional[AIAnalyzer] = None


def _get_analyzer() -> AIAnalyzer:
    """Получает или создаёт глобальный AIAnalyzer instance из config.json."""
    global _analyzer_instance
    if _analyzer_instance is None:
        import os
        _config_path = os.environ.get("CONFIG_PATH", "config.json")
        try:
            with open(_config_path, "r", encoding="utf-8") as _f:
                _cfg = json.load(_f)
            _analyzer_instance = AIAnalyzer(
                api_key=_cfg.get("openai_api_key", ""),
                base_url=_cfg.get("openai_base_url", "https://api.openai.com/v1"),
                model=_cfg.get("openai_model", "gpt-4o-mini"),
            )
        except Exception as e:
            logger.error("Не удалось загрузить config.json для standalone AI: %s", e)
            raise
    return _analyzer_instance


async def analyze_workshop_mod(mod: dict) -> Optional[str]:
    """Standalone функция для анализа мода Workshop."""
    analyzer = _get_analyzer()
    return await analyzer.analyze_workshop_mod(mod)


async def analyze_patch_notes(item: dict) -> Optional[str]:
    """Standalone функция для анализа патчноутов."""
    analyzer = _get_analyzer()
    return await analyzer.analyze_patch_notes(item)
