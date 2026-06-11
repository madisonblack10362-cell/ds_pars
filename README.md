# DayZ Monitor Web — Telegram Mini App

Панель управления для мониторинга новостей DayZ. Открывается прямо из Telegram бота как Web App.

## Возможности
- **Дашборд** — статистика, графики, последние новости
- **Лента новостей** — поиск, фильтрация, пагинация
- **Модерация** — одобрение/отклонение/редактирование перед публикацией
- **Источники** — управление Discord/Telegram/VK/Website
- **Настройки** — AI модель, авто-публикация, интервал

## Деплой на Vercel

1. Импортируйте репозиторий на [vercel.com](https://vercel.com)
2. **Root Directory** = `/` (корень)
3. Добавьте переменные:
   - `JWT_SECRET` = случайный пароль
   - `TELEGRAM_BOT_TOKEN` = токен вашего бота
   - `BOT_API_KEY` = секретный ключ для webhook
   - `DATABASE_URL` = PostgreSQL (Vercel Postgres / Neon)
4. Deploy

## Демо

Логин: `admin` / Пароль: `admin123`

## Интеграция с ботом

Смотрите `web_app_integration.py` — содержит функции для:
- `setup_web_app_button()` — кнопка в меню бота
- `send_to_web_panel()` — отправка новостей на панель
- `get_moderation_status()` — проверка очереди
