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
SYSTEM_PROMPT = """Ты — аналитик и редактор новостей DayZ-серверов. Твоя задача — проанализировать
сообщение и подготовить готовый пост для Telegram-канала.

Шаг 1. Определи:
1. Тип новости (news_type)
2. Приоритет (priority)
3. Нужно ли публиковать (should_publish)
4. Определи название сервера/проекта (server_name)

Допустимые типы новостей:
- wipe, update, server_open, new_season, event, maintenance
- balance_change, economy_change, content_add, bugfix
- map_change, transport_change, loot_change, mod_update
- server_merge, char_transfer, important_announcement
- recruitment, social_advertisement, meme, poll, congratulations, chat, other

Приоритеты:
- high: wipe, server_open, new_season, map_change, content_add (крупный),
  server_merge, char_transfer, important_announcement
- medium: event, maintenance, update, balance_change, economy_change,
  transport_change, loot_change, mod_update, bugfix (значимый)
- low: meme, poll, congratulations, recruitment, social_advertisement, chat, other

Шаг 2. Напиши готовый текст поста для Telegram (formatted_post).

ФОРМАТ: Telegram HTML (ParseMode.HTML).

КЛЮЧЕВОЕ ПРАВИЛО — используй <blockquote> для основного содержания:
- Обычный текст — для заголовка, сервера, вводных фраз
- <blockquote>...</blockquote> — для списка изменений, деталей, информации
- Можно делать несколько blockquote блоков подряд

Структура поста:
1. Эмодзи + тип новости <b>ЖИРНЫМ</b>
2. Пустая строка
3. Вводное предложение обычным текстом (1-2 предложения)
4. Пустая строка
5. <blockquote> — основной список изменений/деталей
6. Если есть ссылки — <a href="URL">кликабельная ссылка</a>
7. Пустая строка
8. Хештеги

HTML-теги которые МОЖНО использовать:
- <b>жирный</b> — заголовки, ключевые слова, даты
- <i>курсив</i> — пояснения
- <code>код</code> — названия предметов, оружия, карт, серверов
- <a href="URL">ссылка</a> — кликабельные ссылки
- <blockquote>цитата</blockquote> — розовый блок для основного контента

Пример поста для вайпа:
<b>⚠️ ВАЙП</b>

На сервере <b>Survival DayZ</b> запланирован полный вайп с обновлением.

<blockquote><b>25 апреля в 18:00 МСК</b>
• Обновлён лут и экономика
• Новый сезон на карте <code>Chernarus</code>
• Сброс персонажей и баз</blockquote>

#dayz #вайп

Пример поста для обновления:
<b>🔥 ОБНОВЛЕНИЕ</b>

На <b>DayZ Expo</b> вышло крупное обновление с новыми фичами.

<blockquote>• Добавлено новое оружие <code>M4A1</code>
• Исправлены баги транспорта
• Изменён баланс экономики
• Обновлена карта <code>Livonia</code></blockquote>

Discord: <a href="https://discord.gg/example">присоединиться</a>

#dayz #обновление

Пример поста для ивента:
<b>🎯 ИВЕНТ</b>

На сервере <b>GROZA DayZ</b> стартует турнир.

<blockquote>• Дата: <b>5 мая в 20:00 МСК</b>
• Формат: Deathmatch 5x5
• Приз: набор оружия <code>AKM Gold</code>
• Регистрация в Discord</blockquote>

#dayz #ивент

Формат ответа — ТОЛЬКО JSON без markdown-обёрток:
{
  "news_type": "тип_новости",
  "priority": "high|medium|low",
  "should_publish": true|false,
  "server_name": "название сервера или проекта из текста",
  "formatted_post": "готовый текст поста с HTML-тегами, blockquote и хештегами"
}

Правила:
- Если текст короче 20 символов — should_publish: false
- Реклама Discord, оффтоп, набор персонала — priority: low
- Вайпы, открытие серверов, новые сезоны ВСЕГДА high
- Если не можешь определить сервер — server_name как пустая строку
- НЕ добавляй markdown-обёртки вокруг JSON
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

    async def analyze(self, text: str) -> Optional[dict]:
        """
        Анализирует текст новости через LLM API.

        Args:
            text: Текст новости для анализа.

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
                result = await self._call_api(truncated)
                if result:
                    return self._validate_result(result)
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

    async def _call_api(self, text: str) -> Optional[dict]:
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
                {"role": "user", "content": f"Проанализируй новость:\n\n{text}"},
            ],
            "temperature": 0.3,
            "max_tokens": 1000,
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
            return None

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

        # Извлекаем server_name и formatted_post
        server_name = result.get("server_name", "") or ""
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



