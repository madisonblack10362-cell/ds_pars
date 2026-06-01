# DayZ News Monitor — Web Panel (Telegram Mini App)

Панель администратора для мониторинга и модерации новостей DayZ. 
Развёрнута на Vercel, открывается как Telegram Web App прямо из бота.

## Возможности

- **Дашборд** — статистика, графики, последние новости
- **Лента новостей** — поиск, фильтрация по типу/приоритету/источнику/статусу
- **Модерация** — просмотр, одобрение, отклонение и редактирование новостей перед публикацией
- **Источники** — управление Discord/Telegram/VK/Website источниками
- **Настройки** — конфигурация AI модели, авто-публикация, интервал проверки

## Технологии

- **Frontend**: Next.js 16 + React + TypeScript + TailwindCSS + shadcn/ui
- **Backend**: Next.js API Routes (serverless на Vercel)
- **База данных**: Prisma ORM + SQLite (локально) / PostgreSQL (Vercel/Neon)
- **Авторизация**: JWT + Telegram Web App initData
- **Деплой**: Vercel

## Быстрый старт

### 1. Установка зависимостей

```bash
cd web
npm install
```

### 2. Настройка переменных окружения

Скопируйте .env.example в .env.local и заполните:

```bash
cp .env.example .env.local
```

Обязательные переменные:
- JWT_SECRET — случайная строка
- TELEGRAM_BOT_TOKEN — токен вашего Telegram бота
- DATABASE_URL — file:./db/dashboard.db (SQLite) или PostgreSQL URL

### 3. Инициализация базы данных

```bash
npx prisma db push
npx prisma db seed
```

### 4. Запуск

```bash
npm run dev
```

**Демо вход**: admin / admin123

## Деплой на Vercel

### 1. Создайте проект на Vercel

1. Зайдите на vercel.com
2. Импортируйте репозиторий GitHub
3. Root Directory установите в `web`
4. Добавьте переменные окружения:
   - JWT_SECRET
   - TELEGRAM_BOT_TOKEN
   - BOT_API_KEY
   - DATABASE_URL (PostgreSQL для production)

### 2. Настройте Telegram Bot

В боте используйте web_app_integration.py:

```python
from web_app_integration import setup_web_app_button, send_to_web_panel

WEB_APP_URL = "https://your-project.vercel.app"
BOT_API_KEY = "your-bot-api-key"

# После запуска бота:
await setup_web_app_button(bot, WEB_APP_URL)

# При получении новости:
await send_to_web_panel(news_data, WEB_APP_URL, BOT_API_KEY)
```

## Структура

```
web/
  src/app/          — Страницы и API routes
  src/components/   — shadcn/ui компоненты
  src/lib/          — Утилиты (auth, db, telegram)
  prisma/           — База данных
  public/           — Статика
  vercel.json       — Конфиг Vercel
```
