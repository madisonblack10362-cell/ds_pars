"""
Модуль базы данных проекта DayZ News Monitor.
Реализует работу с SQLite: создание таблиц, CRUD-операции для новостей,
источников, публикаций и логов.
"""

import aiosqlite
import os
import json
from datetime import datetime, timezone
from typing import Optional

from logger import logger


DB_PATH_DEFAULT = "database/dayz_news.db"


class Database:
    """Асинхронная обёртка над SQLite для хранения данных мониторинга."""

    def __init__(self, db_path: str = DB_PATH_DEFAULT):
        self.db_path = db_path
        self._connection: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        """Создаёт директорию базы данных и устанавливает соединение."""
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        self._connection = await aiosqlite.connect(self.db_path)
        self._connection.row_factory = aiosqlite.Row
        await self._connection.execute("PRAGMA journal_mode=WAL")
        await self._connection.execute("PRAGMA foreign_keys=ON")
        logger.info("Подключение к базе данных: %s", self.db_path)

    async def close(self) -> None:
        """Закрывает соединение с базой данных."""
        if self._connection:
            await self._connection.close()
            logger.info("Соединение с базой данных закрыто")

    async def init_tables(self) -> None:
        """Создаёт все необходимые таблицы, если они не существуют."""
        if not self._connection:
            raise RuntimeError("База данных не инициализирована. Вызовите connect().")

        await self._connection.executescript("""
            -- Таблица источников
            CREATE TABLE IF NOT EXISTS sources (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                source_type     TEXT    NOT NULL,   -- 'discord', 'telegram', 'vk', 'website'
                server_name     TEXT    NOT NULL,
                source_id       TEXT    NOT NULL,   -- ID канала, группы, URL и т.д.
                extra           TEXT    DEFAULT '{}',  -- JSON с дополнительными данными
                created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
                UNIQUE(source_type, source_id)
            );

            -- Таблица собранных сообщений
            CREATE TABLE IF NOT EXISTS messages (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                external_id         TEXT    NOT NULL,   -- ID сообщения в источнике
                source_type         TEXT    NOT NULL,   -- 'discord', 'telegram', 'vk', 'website'
                source_id           TEXT    NOT NULL,   -- ID канала/группы/URL
                server_name         TEXT    NOT NULL,
                channel_name        TEXT    DEFAULT '',
                author              TEXT    DEFAULT '',
                title               TEXT    DEFAULT '',
                text                TEXT    DEFAULT '',
                images              TEXT    DEFAULT '[]',  -- JSON-массив URL-адресов изображений
                links               TEXT    DEFAULT '[]',  -- JSON-массив ссылок
                attachments         TEXT    DEFAULT '[]',  -- JSON-массив вложений
                published_at_source TEXT,                  -- Дата публикации в источнике
                collected_at        TEXT    NOT NULL DEFAULT (datetime('now')),
                UNIQUE(source_type, source_id, external_id)
            );

            -- Таблица обработанных сообщений (результаты AI-анализа)
            CREATE TABLE IF NOT EXISTS processed_messages (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id          INTEGER NOT NULL REFERENCES messages(id),
                news_type           TEXT    DEFAULT '',     -- wipe, update, event, ...
                priority            TEXT    DEFAULT 'low', -- high, medium, low
                should_publish      INTEGER DEFAULT 0,    -- 1 = публиковать, 0 = нет
                summary             TEXT    DEFAULT '',    -- краткое резюме от LLM
                server_name         TEXT    DEFAULT '',    -- определённый AI сервер/проект
                formatted_post      TEXT    DEFAULT '',    -- готовый пост от LLM
                processed_at        TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            -- Таблица опубликованных постов
            CREATE TABLE IF NOT EXISTS published_posts (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id          INTEGER NOT NULL REFERENCES messages(id),
                telegram_message_id INTEGER,             -- ID сообщения в Telegram-канале
                published_at        TEXT    NOT NULL DEFAULT (datetime('now')),
                publish_format      TEXT    DEFAULT '',  -- формат публикации
                UNIQUE(message_id)
            );

            -- Таблица логов (для критичных событий, хранимых в БД)
            CREATE TABLE IF NOT EXISTS logs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                level       TEXT    NOT NULL,
                module      TEXT    NOT NULL,
                message     TEXT    NOT NULL,
                details     TEXT    DEFAULT '',
                created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            -- Таблица подписчиков бота
            CREATE TABLE IF NOT EXISTS bot_users (
                user_id       INTEGER PRIMARY KEY,
                username      TEXT    DEFAULT '',
                first_name    TEXT    DEFAULT '',
                subscribed    INTEGER DEFAULT 1,   -- 1 = подписан, 0 = отписан
                blocked       INTEGER DEFAULT 0,   -- 1 = бот заблокирован юзером
                started_at    TEXT    NOT NULL DEFAULT (datetime('now')),
                updated_at    TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            -- Таблица подписчиков бота
            CREATE TABLE IF NOT EXISTS bot_users (
                user_id       INTEGER PRIMARY KEY,
                username      TEXT    DEFAULT '',
                first_name    TEXT    DEFAULT '',
                subscribed    INTEGER DEFAULT 1,   -- 1 = подписан, 0 = отписан
                blocked       INTEGER DEFAULT 0,   -- 1 = бот заблокирован юзером
                started_at    TEXT    NOT NULL DEFAULT (datetime('now')),
                updated_at    TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            -- Индексы для ускорения запросов
            CREATE INDEX IF NOT EXISTS idx_messages_source ON messages(source_type, source_id);
            CREATE INDEX IF NOT EXISTS idx_messages_collected ON messages(collected_at);
            CREATE INDEX IF NOT EXISTS idx_messages_external ON messages(source_type, source_id, external_id);
            CREATE INDEX IF NOT EXISTS idx_processed_publish ON processed_messages(should_publish);
            CREATE INDEX IF NOT EXISTS idx_published_message ON published_posts(message_id);
        """)
        await self._connection.commit()
        logger.info("Таблицы базы данных созданы/проверены")

    # -------------------------------------------------------------------------
    # Источники
    # -------------------------------------------------------------------------

    async def register_source(
        self,
        source_type: str,
        server_name: str,
        source_id: str,
        extra: dict | None = None,
    ) -> int:
        """Регистрирует новый источник. Возвращает id записи."""
        extra_json = json.dumps(extra or {}, ensure_ascii=False)
        cursor = await self._connection.execute(
            """INSERT OR IGNORE INTO sources (source_type, server_name, source_id, extra)
               VALUES (?, ?, ?, ?)""",
            (source_type, server_name, source_id, extra_json),
        )
        await self._connection.commit()
        return cursor.lastrowid

    async def get_sources(self, source_type: str | None = None) -> list[dict]:
        """Возвращает список источников, опционально отфильтрованный по типу."""
        if source_type:
            rows = await self._connection.execute(
                "SELECT * FROM sources WHERE source_type = ?", (source_type,)
            )
        else:
            rows = await self._connection.execute("SELECT * FROM sources")
        return [dict(row) for row in await rows.fetchall()]

    # -------------------------------------------------------------------------
    # Сообщения
    # -------------------------------------------------------------------------

    async def save_message(
        self,
        external_id: str,
        source_type: str,
        source_id: str,
        server_name: str,
        text: str,
        title: str = "",
        channel_name: str = "",
        author: str = "",
        images: list[str] | None = None,
        links: list[str] | None = None,
        attachments: list[str] | None = None,
        published_at_source: str | None = None,
    ) -> int | None:
        """
        Сохраняет новое сообщение в базу. Возвращает id записи или None,
        если сообщение уже существует (дубликат).
        """
        images_json = json.dumps(images or [], ensure_ascii=False)
        links_json = json.dumps(links or [], ensure_ascii=False)
        attachments_json = json.dumps(attachments or [], ensure_ascii=False)

        try:
            cursor = await self._connection.execute(
                """INSERT INTO messages
                   (external_id, source_type, source_id, server_name,
                    channel_name, author, title, text, images, links, attachments,
                    published_at_source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    external_id,
                    source_type,
                    source_id,
                    server_name,
                    channel_name,
                    author,
                    title,
                    text,
                    images_json,
                    links_json,
                    attachments_json,
                    published_at_source,
                ),
            )
            await self._connection.commit()
            logger.debug(
                "Сообщение сохранено: source=%s id=%s server=%s",
                source_type,
                external_id,
                server_name,
            )
            return cursor.lastrowid
        except aiosqlite.IntegrityError:
            logger.debug(
                "Дубликат сообщения проигнорирован: source=%s id=%s",
                source_type,
                external_id,
            )
            return None

    async def get_unprocessed_messages(self, limit: int = 50) -> list[dict]:
        """Возвращает сообщения, ещё не прошедшие AI-анализ."""
        cursor = await self._connection.execute(
            """SELECT m.* FROM messages m
               LEFT JOIN processed_messages pm ON m.id = pm.message_id
               WHERE pm.id IS NULL
               ORDER BY m.collected_at DESC
               LIMIT ?""",
            (limit,),
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def get_message_by_id(self, message_id: int) -> dict | None:
        """Возвращает сообщение по внутреннему id."""
        cursor = await self._connection.execute(
            "SELECT * FROM messages WHERE id = ?", (message_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_recent_messages(
        self, hours: int = 24, limit: int = 100
    ) -> list[dict]:
        """Возвращает сообщения за последние N часов."""
        cursor = await self._connection.execute(
            """SELECT * FROM messages
               WHERE collected_at >= datetime('now', ?)
               ORDER BY collected_at DESC
               LIMIT ?""",
            (f"-{hours} hours", limit),
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def get_all_messages_texts(self) -> list[tuple[int, str]]:
        """Возвращает пары (message_id, text) всех сообщений для дедупликации."""
        cursor = await self._connection.execute(
            "SELECT id, text FROM messages WHERE length(text) > 10"
        )
        return [(row["id"], row["text"]) for row in await cursor.fetchall()]

    # -------------------------------------------------------------------------
    # Обработанные сообщения
    # -------------------------------------------------------------------------

    async def save_processed(
        self,
        message_id: int,
        news_type: str,
        priority: str,
        should_publish: bool,
        summary: str,
        server_name: str = "",
        formatted_post: str = "",
    ) -> None:
        """Сохраняет результаты AI-анализа сообщения."""
        await self._connection.execute(
            """INSERT INTO processed_messages
               (message_id, news_type, priority, should_publish, summary,
                server_name, formatted_post)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (message_id, news_type, priority, int(should_publish), summary,
             server_name, formatted_post),
        )
        await self._connection.commit()
        logger.debug(
            "Сообщение #%d обработано: type=%s priority=%s publish=%s",
            message_id,
            news_type,
            priority,
            should_publish,
        )

    async def get_pending_publish(self, limit: int = 20) -> list[dict]:
        """Возвращает сообщения, рекомендованные к публикации, но ещё не опубликованные."""
        cursor = await self._connection.execute(
            """SELECT m.*, pm.news_type, pm.priority, pm.summary,
                      pm.server_name as ai_server_name, pm.formatted_post
               FROM messages m
               INNER JOIN processed_messages pm ON m.id = pm.message_id
               LEFT JOIN published_posts pp ON m.id = pp.message_id
               WHERE pm.should_publish = 1 AND pp.id IS NULL
               ORDER BY m.collected_at DESC
               LIMIT ?""",
            (limit,),
        )
        return [dict(row) for row in await cursor.fetchall()]

    # -------------------------------------------------------------------------
    # Опубликованные посты
    # -------------------------------------------------------------------------

    async def mark_published(
        self, message_id: int, telegram_message_id: int, publish_format: str = ""
    ) -> None:
        """Отмечает сообщение как опубликованное."""
        await self._connection.execute(
            """INSERT OR IGNORE INTO published_posts
               (message_id, telegram_message_id, publish_format)
               VALUES (?, ?, ?)""",
            (message_id, telegram_message_id, publish_format),
        )
        await self._connection.commit()
        logger.info("Сообщение #%d отмечено как опубликованное (TG msg_id=%d)", message_id, telegram_message_id)

    async def is_published(self, message_id: int) -> bool:
        """Проверяет, было ли сообщение уже опубликовано."""
        cursor = await self._connection.execute(
            "SELECT 1 FROM published_posts WHERE message_id = ?", (message_id,)
        )
        row = await cursor.fetchone()
        return row is not None

    # -------------------------------------------------------------------------
    # Статистика для сводки
    # -------------------------------------------------------------------------

    async def get_daily_stats(self, hours: int = 24) -> dict:
        """Возвращает статистику за последние N часов."""
        cursor = await self._connection.execute(
            """SELECT
                   COUNT(*) as total,
                   SUM(CASE WHEN pm.priority = 'high' THEN 1 ELSE 0 END) as high_count,
                   SUM(CASE WHEN pm.priority = 'medium' THEN 1 ELSE 0 END) as medium_count,
                   SUM(CASE WHEN pm.priority = 'low' THEN 1 ELSE 0 END) as low_count,
                   SUM(CASE WHEN pp.id IS NOT NULL THEN 1 ELSE 0 END) as published_count
               FROM messages m
               LEFT JOIN processed_messages pm ON m.id = pm.message_id
               LEFT JOIN published_posts pp ON m.id = pp.message_id
               WHERE m.collected_at >= datetime('now', ?)""",
            (f"-{hours} hours",),
        )
        row = await cursor.fetchone()
        return dict(row) if row else {}

    async def get_daily_events(self, hours: int = 24) -> list[dict]:
        """Возвращает важные события за последние N часов для сводки."""
        cursor = await self._connection.execute(
            """SELECT m.server_name, m.title, m.text, pm.news_type, pm.priority, pm.summary
               FROM messages m
               INNER JOIN processed_messages pm ON m.id = pm.message_id
               WHERE m.collected_at >= datetime('now', ?)
                 AND pm.priority IN ('high', 'medium')
               ORDER BY pm.priority DESC, m.collected_at DESC
               LIMIT 15""",
            (f"-{hours} hours",),
        )
        return [dict(row) for row in await cursor.fetchall()]

    # -------------------------------------------------------------------------
    # Подписчики бота
    # -------------------------------------------------------------------------

    async def register_bot_user(self, user_id: int, username: str = "", first_name: str = "") -> None:
        """Регистрирует юзера бота. Если уже есть — обновляет username/first_name."""
        await self._connection.execute(
            """INSERT INTO bot_users (user_id, username, first_name)
               VALUES (?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                 username = excluded.username,
                 first_name = excluded.first_name,
                 updated_at = datetime('now')""",
            (user_id, username or "", first_name or ""),
        )
        await self._connection.commit()

    async def subscribe_user(self, user_id: int) -> bool:
        """Включает подписку юзеру. Возвращает True если юзер существовал."""
        cursor = await self._connection.execute(
            """UPDATE bot_users SET subscribed = 1, blocked = 0, updated_at = datetime('now')
               WHERE user_id = ?""",
            (user_id,),
        )
        await self._connection.commit()
        return cursor.rowcount > 0

    async def unsubscribe_user(self, user_id: int) -> bool:
        """Отключает подписку."""
        cursor = await self._connection.execute(
            """UPDATE bot_users SET subscribed = 0, updated_at = datetime('now')
               WHERE user_id = ?""",
            (user_id,),
        )
        await self._connection.commit()
        return cursor.rowcount > 0

    async def mark_user_blocked(self, user_id: int) -> None:
        """Отмечает юзера как заблокировавший бота."""
        await self._connection.execute(
            """UPDATE bot_users SET blocked = 1, subscribed = 0, updated_at = datetime('now')
               WHERE user_id = ?""",
            (user_id,),
        )
        await self._connection.commit()

    async def get_all_subscribers(self) -> list[dict]:
        """Возвращает всех активных подписчиков (не заблокированных)."""
        cursor = await self._connection.execute(
            """SELECT user_id, username, first_name FROM bot_users
               WHERE subscribed = 1 AND blocked = 0"""
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def get_subscriber_count(self) -> int:
        """Возвращает количество активных подписчиков."""
        cursor = await self._connection.execute(
            "SELECT COUNT(*) as cnt FROM bot_users WHERE subscribed = 1 AND blocked = 0"
        )
        row = await cursor.fetchone()
        return row["cnt"] if row else 0

    async def is_user_subscribed(self, user_id: int) -> bool:
        """Проверяет, подписан ли юзер."""
        cursor = await self._connection.execute(
            "SELECT subscribed FROM bot_users WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        return bool(row and row["subscribed"])

    # -------------------------------------------------------------------------
    # Логи в БД
    # -------------------------------------------------------------------------

    async def log_to_db(
        self, level: str, module: str, message: str, details: str = ""
    ) -> None:
        """Сохраняет критичное событие в таблицу логов базы данных."""
        await self._connection.execute(
            """INSERT INTO logs (level, module, message, details)
               VALUES (?, ?, ?, ?)""",
            (level, module, message, details),
        )
        await self._connection.commit()
