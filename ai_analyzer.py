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


# Промпт для Reddit-постов — переводит на русский и адаптирует формат
REDDIT_SYSTEM_PROMPT = """Ты — креативный редактор новостного Telegram-канала про DayZ. Ты берёшь посты с Reddit и делаешь из них интересные, короткие посты на русском.

ГЛАВНОЕ ПРАВИЛО: Пост должен быть ИНТЕРЕСНЫМ. Если исходный пост скучный, банальный или не несёт пользы — ставь should_publish: false.

ЧТО ИНТЕРЕСНО (should_publish: true):
- Обновления игры (патчи, новые фичи, фиксы)
- Важные баги и эксплоиты
- Обновления популярных модов, новые кастомные карты
- Интересные гайды, лайфхаки, механики о которых мало кто знает
- Крутые истории выживания (не банальные "я нашёл винтовку")
- Обсуждения с умными инсайтами о механиках DayZ

ЧТО НЕ ИНТЕРЕСНО (should_publish: false, news_type: other, priority: low):
- Хвастовство лутом ("look what I found")
- Банальные скриншоты игры
- Вопросы новичков ("how do I craft")
- Мемы и смешные видео (unless really good)
- Рандомные мысли без содержания
- Посты-жалобы ("this game is dead")
- Повторные посты о том же самом

ТИПЫ КОНТЕНТА (news_type):
- update — обновление игры, патч, новые фичи
- wipe — вайп серверов
- event — ивент, турнир
- discussion — интересное обсуждение с умными мыслями
- content — хороший гайд, лайфхак, полезный совет
- mod — новый мод, обновление мода, кастомная карта, SPT
- story — крутая история выживания
- bug — важный баг, эксплоит
- meme — мем (только если реально смешной)
- other — скучное/банальное (should_publish: false)

ПРИОРИТЕТЫ:
- high: крупное обновление DayZ, официальный анонс Bohemia
- medium: хорошие гайды, обсуждения, патчи, моды
- low: мемы, скрины, хвастовство, банальщина

ФОРМАТ ПОСТА:

1. НА РУССКОМ ЯЗЫКЕ. Названия предметов/оружия в <code> на английском.
2. НЕ упоминай Reddit. НЕ ставь ссылок на Reddit. Без "📰 Reddit" в начале.
3. Формат:

<b>ЭМОДЗИ ТИП</b>

<blockquote>Кратко и по делу, 2-4 предложения. Без воды. Только суть и интересные детали.</blockquote>

#dayz #тип

4. Эмодзи: update 🔄, wipe ⚠️, event 🎉, discussion 💬, content 💡, mod 🔧, story 📖, bug 🐛
5. ОДИН <blockquote>. Без лишних ссылок. Без "подробнее по ссылке".

ПРИМЕРЫ:

Исходный: "DayZ 1.25 Update 2 is now live. Helicopter physics reworked, infected AI improved, Hunter scope added."
{
  "news_type": "update",
  "priority": "high",
  "should_publish": true,
  "server_name": "Reddit",
  "server_link": "",
  "formatted_post": "<b>🔄 ОБНОВЛЕНИЕ</b>\\n\\n<blockquote>Вышло обновление <b>DayZ 1.25 Update 2</b>.\\n\\n• Новая физика вертолётов\\n• Переработанный AI заражённых\\n• Прицел <code>Hunter scope</code>\\n</blockquote>\\n\\n#dayz #обновление"
}

Исходный: "Found this M4 in a barn on officials lol"
{
  "news_type": "other",
  "priority": "low",
  "should_publish": false,
  "server_name": "Reddit",
  "server_link": "",
  "formatted_post": "",
  "summary": "Банальный пост — хвастовство лутом"
}

Исходный: "Anyone else feel night is unplayable now? Since 1.24 gamma exploit got fixed you need NVGs"
{
  "news_type": "discussion",
  "priority": "medium",
  "should_publish": true,
  "server_name": "Reddit",
  "server_link": "",
  "formatted_post": "<b>💬 ОБСУЖДЕНИЕ</b>\\n\\n<blockquote>После патча <b>1.24</b> ночное время стало реально тёмным — исправили эксплоит с гаммой. Теперь без <code>ПНВ</code> или фонарика играть ночью почти невозможно.\\n</blockquote>\\n\\n#dayz #обсуждение"
}

Формат ответа — ТОЛЬКО JSON без markdown.
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
                    attempt,
                    self.max_retries,
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

        # Низкоприоритетные новости не публикуем
        if priority == "low":
            should_publish = False

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

    async def analyze_reddit(self, text: str, author: str = "", subreddit: str = "") -> Optional[dict]:
        """
        Анализирует Reddit-пост через LLM с отдельным промптом для Reddit-контента.

        Args:
            text: Текст Reddit-поста (может быть на английском).
            author: Имя автора поста (Reddit username).
            subreddit: Название сабреддита.

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

        truncated = text[:4000] if len(text) > 4000 else text

        for attempt in range(1, self.max_retries + 1):
            try:
                result = await self._call_api_reddit(truncated, author, subreddit)
                if result:
                    return self._validate_result(result)
                logger.warning("Попытка %d/%d: LLM (Reddit) вернул пустой результат", attempt, self.max_retries)
            except Exception as exc:
                logger.warning(
                    "Попытка %d/%d анализа Reddit через LLM не удалась: %s",
                    attempt, self.max_retries, exc,
                )
            if attempt < self.max_retries:
                await asyncio.sleep(2 ** attempt)

        logger.error("Не удалось проанализировать Reddit-пост через LLM после %d попыток", self.max_retries)
        return None

    async def _call_api_reddit(self, text: str, author: str = "", subreddit: str = "") -> Optional[dict]:
        """Выполняет запрос к API с Reddit-промптом."""
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        meta = f"[АВТОР: u/{author}]"
        if subreddit:
            meta += f" [САБРЕДДИТ: r/{subreddit}]"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": REDDIT_SYSTEM_PROMPT},
                {"role": "user", "content": f"Проанализируй Reddit-пост:\n{meta}\n\n{text}"},
            ],
            "temperature": 0.3,
            "max_tokens": 2048,
        }

        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status != 200:
                    body = await response.text()
                    logger.error(
                        "LLM API (Reddit) вернул статус %d: %s", response.status, body[:500]
                    )
                    return None

                data = await response.json()
                content = data["choices"][0]["message"]["content"]
                parsed = self._parse_llm_json(content)
                if parsed is None:
                    logger.warning("Не удалось распарсить JSON от LLM (Reddit): %s", content[:300])
                return parsed

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



