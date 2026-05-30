"""
Модуль AI-анализа новостей проекта DayZ News Monitor.
Использует OpenAI API для определения типа новости, приоритета,
необходимости публикации и генерации краткого резюме.
"""

import json
from typing import Optional

import aiohttp

from logger import logger


# Системный промпт для LLM — задаёт контекст и правила классификации
SYSTEM_PROMPT = """Ты — аналитик новостей DayZ-серверов. Твоя задача — анализировать
сообщения из Discord, Telegram, VK и сайтов проектов и определять:

1. Тип новости (news_type)
2. Приоритет (priority)
3. Нужно ли публиковать (should_publish)
4. Краткое резюме (summary)

Допустимые типы новостей:
- wipe (вайп — полный или частичный)
- update (обновление сервера/моды)
- server_open (открытие сервера)
- new_season (новый сезон)
- event (ивент, турнир, конкурс)
- maintenance (технические работы)
- balance_change (балансные изменения)
- economy_change (изменение экономики)
- content_add (добавление нового контента)
- bugfix (исправление ошибок)
- map_change (изменение карты)
- transport_change (изменение транспорта)
- loot_change (изменение лута)
- mod_update (обновление модов)
- server_merge (слияние серверов)
- char_transfer (перенос персонажей)
- important_announcement (важное заявление администрации)
- recruitment (набор модераторов/админов)
- social_advertisement (реклама Discord/соцсетей)
- meme (мемы/флуд)
- poll (опрос)
- congratulations (поздравления)
- chat (обычное общение)
- other (прочее)

Приоритеты:
- high: wipe, server_open, new_season, map_change, content_add (крупный),
  server_merge, char_transfer, important_announcement, крупное обновление
- medium: event, maintenance, update, balance_change, economy_change,
  transport_change, loot_change, mod_update, bugfix (значимый)
- low: meme, poll, congratulations, recruitment, social_advertisement,
  chat, other

Формат ответа — ТОЛЬКО JSON без markdown-обёрток:
{
  "news_type": "тип_новости",
  "priority": "high|medium|low",
  "should_publish": true|false,
  "summary": "Краткое резюме новости на русском языке, 1-3 предложения"
}

Правила:
- Если текст короче 20 символов или не содержит полезной информации — should_publish: false
- Если сообщение содержит набор персонала, рекламу Discord или оффтоп — priority: low
- Вайпы, открытие серверов, новые сезоны ВСЕГДА high приоритет
- Резюме должно быть информативным и кратким
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
                    await asyncio_sleep(2 ** attempt)

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
            "temperature": 0.2,
            "max_tokens": 500,
            "response_format": {"type": "json_object"},
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
                return json.loads(content)

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

        return {
            "news_type": news_type,
            "priority": priority,
            "should_publish": should_publish,
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
            "response_format": {"type": "json_object"},
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


async def asyncio_sleep(seconds: float) -> None:
    """Импортируем asyncio.sleep вruntime-контексте."""
    import asyncio
    await asyncio.sleep(seconds)
