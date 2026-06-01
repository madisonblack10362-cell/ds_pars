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

ПРАВИЛА КЛАССИФИКАЦИИ (САМОЕ ВАЖНОЕ):

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

ПРАВИЛА КРАСОТЫХ ПОСТОВ:

1. НЕ ПРИДУМЫВАЙ текст. ПЕРЕПИСЫВАЙ исходный текст красиво, но СОХРАНЯЙ ВСЕ ФАКТЫ.
2. НЕ ДОБАВЛЯЙ слова типа "наш", "запланирован" если их нет в оригинале.
3. СОХРАНЯЙ все даты, времена, IP-адреса, названия серверов, ссылки.
4. Заголовок: эмодзи + тип новости <b>ЖИРНЫМ</b>
5. Вводное предложение: обычный текст, 1-2 предложения, из оригинала
6. Делай ОТДЕЛЬНЫЙ <blockquote> ДЛЯ КАЖДОЙ СЕКЦИИ:
   - Добавлено/Изменено/Исправлено/Новый сервер — каждый в свой blockquote
   - Внутри blockquote начни с <b>жирного заголовка секции</b> с эмодзи
   - Между blockquote блоками — пустая строка
7. <code>код</code> — для названий предметов, оружия, карт, IP-адресов
8. <b>жирный</b> — для дат, ключевых слов, заголовков секций
9. <a href="URL">ссылка</a> — кликабельные ссылки
10. Хештеги в конце: #dayz + релевантный тип

ПРИМЕР ПРАВИЛЬНОГО ПОСТА (из реальной новости):
Исходная: "Уже завтра произойдет вайп. Добавлена новая постройка Дом на дереве. Изменено количество хп частокола. Улучшен античит. Новая карта Namalsk IP 185.189.255.190:2705."

JSON ответ:
{
  "news_type": "wipe",
  "priority": "high",
  "should_publish": true,
  "server_name": "DayZ",
  "formatted_post": "<b>⚠️ ВАЙП</b>\n\nУже завтра произойдет вайп, под него выпущено обновление.\n\n<blockquote><b>➕ Добавлено</b>\n• Постройка <code>Дом на дереве</code> с хп как у частокола\n• Карта <code>Namalsk</code> для нового сервера</blockquote>\n\n<blockquote><b>🔧 Изменено</b>\n• Количество хп частокола +50% прочности\n• Добавлено ~20% хп сооружениям\n• Полностью обновлена стройка</blockquote>\n\n<blockquote><b>✅ Исправлено</b>\n• Улучшен античит\n• Переводы и мелкие баги</blockquote>\n\n<blockquote><b>🎮 Новый сервер</b>\nОт первого лица на <code>Namalsk</code>\n<code>185.189.255.190:2705</code></blockquote>\n\n#dayz #вайп"
}

НЕПРАВИЛЬНЫЕ ПРИМЕРЫ (НЕЛЬЗЯ делать):
❌ "На сервере DayZ запланирован полный вайп" — не придумывай
❌ "Сегодня" когда в оригинале "завтра" — не меняй даты
❌ "Улучшен наш античит" — не добавляй "наш"
❌ wipe для каждого поста — большинство новостей это update
❌ Один большой blockquote на всё — делай отдельные секции

Формат ответа — ТОЛЬКО JSON без markdown-обёрток:
{"news_type": "...", "priority": "...", "should_publish": true/false, "server_name": "...", "formatted_post": "HTML с несколькими blockquote секциями"}
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

        # Ищем HTML-пост — весь текст после <b>...</b>
        formatted_post = ""
        html_match = re.search(r"(<b>[^<]+</b>.*?)(?=#\w|$)", text, re.DOTALL | re.IGNORECASE)
        if html_match:
            formatted_post = html_match.group(1).strip()

        # Если не нашли HTML — ищем JSON-подобный фрагмент с formatted_post
        if not formatted_post:
            fp_match = re.search(r'"formatted_post"[:\s]*"(.+?)"', text, re.DOTALL)
            if fp_match:
                formatted_post = fp_match.group(1).strip()
                formatted_post = formatted_post.replace('\\n', '\n').replace('\\"', '"')

        logger.info("LLM фоллбэк: извлечено из текста — type=%s, priority=%s, publish=%s",
                    news_type, priority, should_publish)

        return {
            "news_type": news_type,
            "priority": priority,
            "should_publish": should_publish,
            "server_name": server_name[:200],
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



