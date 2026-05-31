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

Шаг 2. Напиши готовый текст поста для Telegram (formatted_post).

Правила оформления поста:
- Пиши на русском языке
- Используй подходящие эмодзи
- Структура:
  Заголовок (эмодзи + тип новости)
  Пустая строка
  Название сервера/проекта (если удалось определить из текста)
  Пустая строка
  Основное содержание — перепиши новость красиво, коротко и по делу.
  Используй списки с bullet points (начинай строки с \u2022)
  Не пиши больше 1500 символов.
  Пустая строка
  Хештеги: #dayz и релевантные (например #вайп, #обновление, #ивент)
- Убери лишнюю воду, повторения, оффтоп
- Сохрани все важные факты: даты, числа, названия
- Не выдумывай информацию которой нет в исходном тексте
- Если новость о вайпе — выдели дату и время вайпа
- Если новость об обновлении — перечисли ключевые изменения

Пример поста для вайпа:
\u26a0\ufe0f ВАЙП
\n\U0001f3ae Survival DayZ
\n\u2022 Вайп scheduled на 25 апреля в 18:00 МСК
\u2022 Обновлён лут и экономика
\u2022 Новый сезон
\n#dayz #вайп

Пример поста для обновления:
\U0001f525 ОБНОВЛЕНИЕ
\n\U0001f3ae DayZ Expo
\n\u2022 Добавлено новое оружие M4A1
\u2022 Исправлены баги транспорта
\u2022 Изменён баланс экономики
\n#dayz #обновление

Формат ответа — ТОЛЬКО JSON без markdown-обёрток:
{
  "news_type": "тип_новости",
  "priority": "high|medium|low",
  "should_publish": true|false,
  "server_name": "название сервера или проекта из текста",
  "formatted_post": "готовый текст поста для Telegram с эмодзи и хештегами"
}

Правила:
- Если текст короче 20 символов или не содержит полезной информации — should_publish: false
- Если сообщение содержит набор персонала, рекламу Discord или оффтоп — priority: low
- Вайпы, открытие серверов, новые сезоны ВСЕГДА high приоритет
- Если не можешь определить сервер — пиши server_name как пустую строку
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



