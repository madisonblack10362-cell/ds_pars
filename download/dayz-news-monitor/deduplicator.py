"""
Модуль дедупликации новостей проекта DayZ News Monitor.
Определяет дубликаты с помощью косинусного сходства текстов,
LLM-проверки и сравнения изображений.
"""

import json
import hashlib
from typing import Optional

import numpy as np

from database import Database
from ai_analyzer import AIAnalyzer
from logger import logger


def _simple_tokenizer(text: str) -> list[str]:
    """
    Простой токенизатор: разбивает текст на слова, приводя к нижнему регистру.
    Отбрасывает слова короче 2 символов.
    """
    words = text.lower().split()
    return [w.strip(".,!?;:()-—\"'«»") for w in words if len(w.strip(".,!?;:()-—\"'«»")) >= 2]


def _build_word_set(text: str) -> set[str]:
    """Строит множество уникальных токенов из текста."""
    return set(_simple_tokenizer(text))


def _cosine_similarity(set1: set[str], set2: set[str]) -> float:
    """
    Вычисляет косинусное сходство двух множеств токенов (bag-of-words).
    Возвращает значение от 0.0 до 1.0.
    """
    if not set1 or not set2:
        return 0.0

    # Union — все уникальные слова из обоих текстов
    all_words = set1 | set2
    if not all_words:
        return 0.0

    # Bag-of-words векторы
    vec1 = np.array([1 if w in set1 else 0 for w in all_words], dtype=np.float64)
    vec2 = np.array([1 if w in set2 else 0 for w in all_words], dtype=np.float64)

    dot_product = np.dot(vec1, vec2)
    norm1 = np.linalg.norm(vec1)
    norm2 = np.linalg.norm(vec2)

    if norm1 == 0 or norm2 == 0:
        return 0.0

    return float(dot_product / (norm1 * norm2))


def compute_text_hash(text: str) -> str:
    """
    Вычисляет SHA-256 хеш нормализованного текста.
    Используется для быстрого обнаружения точных дубликатов.
    """
    normalized = " ".join(sorted(_simple_tokenizer(text)))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def compute_image_hashes(image_urls: list[str]) -> set[str]:
    """Вычисляет SHA-256 хеши URL-адресов изображений для сравнения."""
    return {hashlib.sha256(url.encode("utf-8")).hexdigest() for url in image_urls}


class Deduplicator:
    """
    Определяет дубликаты новостей с использованием:
    1. Точных хешей (быстрая проверка)
    2. Косинусного сходства текстов
    3. Сравнения множеств изображений
    4. LLM-проверки (при спорных случаях)
    """

    def __init__(
        self,
        db: Database,
        ai_analyzer: AIAnalyzer | None = None,
        similarity_threshold: float = 0.85,
    ):
        self.db = db
        self.ai_analyzer = ai_analyzer
        self.similarity_threshold = similarity_threshold
        # Кэш хешей для быстрой проверки
        self._hash_cache: dict[str, int] = {}
        self._image_hash_cache: dict[str, int] = {}

    async def is_duplicate(
        self,
        message_id: int,
        text: str,
        images: list[str] | None = None,
    ) -> Optional[int]:
        """
        Проверяет, является ли сообщение дубликатом уже сохранённого.

        Args:
            message_id: ID сообщения в БД (исключается из проверки).
            text: Текст новости.
            images: Список URL-адресов изображений.

        Returns:
            ID существующего сообщения-оригинала, если дубликат найден,
            иначе None.
        """
        # 1. Быстрая проверка по хешу текста
        text_hash = compute_text_hash(text)
        if text_hash in self._hash_cache:
            existing_id = self._hash_cache[text_hash]
            if existing_id != message_id:
                logger.debug(
                    "Точный дубликат по хешу текста: новый #%d = существующий #%d",
                    message_id,
                    existing_id,
                )
                return existing_id

        # 2. Проверка по пересечению изображений
        if images:
            new_img_hashes = compute_image_hashes(images)
            for cached_hash, cached_msg_id in self._image_hash_cache.items():
                if cached_msg_id == message_id:
                    continue
                if cached_hash in new_img_hashes and len(new_img_hashes) >= 2:
                    # Более 50% изображений совпадают — вероятный дубликат
                    overlap = len(new_img_hashes & self._get_msg_image_hashes(cached_msg_id))
                    if overlap >= len(new_img_hashes) * 0.5:
                        logger.debug(
                            "Дубликат по изображениям: новый #%d ~ #%d (%d общих фото)",
                            message_id,
                            cached_msg_id,
                            overlap,
                        )
                        return cached_msg_id

        # 3. Косинусное сходство с существующими сообщениями
        new_tokens = _build_word_set(text)
        if not new_tokens:
            return None

        all_messages = await self.db.get_all_messages_texts()
        best_match_id = None
        best_score = 0.0

        for existing_id, existing_text in all_messages:
            if existing_id == message_id:
                continue
            if len(existing_text) < 15:
                continue

            existing_tokens = _build_word_set(existing_text)
            score = _cosine_similarity(new_tokens, existing_tokens)

            if score > best_score:
                best_score = score
                best_match_id = existing_id

        if best_score >= self.similarity_threshold:
            logger.info(
                "Дубликат по косинусному сходству: новый #%d ~ #%d (score=%.2f)",
                message_id,
                best_match_id,
                best_score,
            )
            return best_match_id

        # 4. LLM-проверка для спорных случаев (0.60 <= score < 0.85)
        if (
            self.ai_analyzer
            and best_score >= 0.60
            and best_match_id is not None
        ):
            existing_msg = await self.db.get_message_by_id(best_match_id)
            if existing_msg:
                llm_result = await self.ai_analyzer.check_similarity(
                    text, existing_msg["text"]
                )
                if llm_result and llm_result.get("is_duplicate"):
                    logger.info(
                        "Дубликат по LLM-проверке: новый #%d ~ #%d (reason: %s)",
                        message_id,
                        best_match_id,
                        llm_result.get("reason", ""),
                    )
                    return best_match_id

        # Кэшируем хеш нового сообщения
        self._hash_cache[text_hash] = message_id
        if images:
            for img_url in images:
                img_hash = hashlib.sha256(img_url.encode("utf-8")).hexdigest()
                self._image_hash_cache[img_hash] = message_id

        return None

    async def mark_as_duplicate(
        self, original_id: int, duplicate_id: int
    ) -> None:
        """
        Отмечает duplicate_id как дубликат original_id.
        Записывает в processed_messages с should_publish=0 и пометкой дубликата.
        """
        await self.db.save_processed(
            message_id=duplicate_id,
            news_type="duplicate",
            priority="low",
            should_publish=False,
            summary=f"Дубликат сообщения #{original_id}",
        )
        logger.info(
            "Сообщение #%d отмечено как дубликат #%d", duplicate_id, original_id
        )

    async def warm_cache(self) -> None:
        """Предзагружает кэш хешей из базы данных при запуске."""
        all_messages = await self.db.get_all_messages_texts()
        self._hash_cache.clear()
        self._image_hash_cache.clear()

        for msg_id, text in all_messages:
            text_hash = compute_text_hash(text)
            self._hash_cache[text_hash] = msg_id

            # Загружаем хеши изображений
            msg = await self.db.get_message_by_id(msg_id)
            if msg:
                try:
                    images = json.loads(msg.get("images", "[]"))
                    for img_url in images:
                        img_hash = hashlib.sha256(
                            img_url.encode("utf-8")
                        ).hexdigest()
                        self._image_hash_cache[img_hash] = msg_id
                except (json.JSONDecodeError, TypeError):
                    pass

        logger.info(
            "Кэш дедупликатора загружен: %d текстовых хешей, %d хешей изображений",
            len(self._hash_cache),
            len(self._image_hash_cache),
        )

    def _get_msg_image_hashes(self, msg_id: int) -> set[str]:
        """Возвращает множество хешей изображений для сообщения из кэша."""
        return {
            h for h, mid in self._image_hash_cache.items() if mid == msg_id
        }
