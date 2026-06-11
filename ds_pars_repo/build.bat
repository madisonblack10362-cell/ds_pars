@echo off
chcp 65001 >nul
title DayZ Monitor — Build .exe
color 0E

cd /d "%~dp0"

echo.
echo  =====================================================
echo    DayZ News Monitor — Сборка .exe
echo  =====================================================
echo.

:: Проверяем что бот не запущен
tasklist /FI "IMAGENAME eq DayZ Monitor.exe" 2>nul | find /I "DayZ Monitor.exe" >nul
if not errorlevel 1 (
    echo  [ОШИБКА] DayZ Monitor.exe УЖЕ ЗАПУЩЕН!
    echo  Закрой бота перед сборкой, иначе файлы заблокированы.
    echo.
    pause
    exit /b 1
)

:: Проверяем Python
where python >nul 2>&1
if errorlevel 1 (
    echo  [ОШИБКА] Python не найден!
    echo  Скачай с https://www.python.org/downloads/
    echo  При установке поставь галочку "Add Python to PATH"
    echo.
    pause
    exit /b 1
)

echo  [1/3] Установка зависимостей...
echo.
python -m pip install --upgrade pip --quiet
python -m pip install -q ^
    aiohttp>=3.9.5 ^
    aiogram>=3.4.1 ^
    aiosqlite>=0.20.0 ^
    telethon>=1.36.0 ^
    "discord.py-self>=2.0.0" ^
    apscheduler>=3.10.4 ^
    beautifulsoup4>=4.12.3 ^
    lxml>=5.2.2 ^
    feedparser>=6.0.11 ^
    openai>=1.30.0 ^
    numpy>=1.26.4 ^
    aiofiles>=23.2.1 ^
    customtkinter>=5.2.0 ^
    httpx>=0.27.0 ^
    pyinstaller>=6.0.0

if errorlevel 1 (
    echo.
    echo  [ОШИБКА] Не удалось установить зависимости!
    echo  Попробуй запустить build.bat от имени администратора
    echo.
    pause
    exit /b 1
)

echo  Зависимости установлены.
echo.
echo  [2/3] Сборка .exe через PyInstaller...
echo  Это может занять 2-5 минут...
echo.

python build.py

if errorlevel 1 (
    echo.
    echo  [ОШИБКА] Сборка завершена с ошибкой!
    echo  Смотри лог выше.
    echo.
    pause
    exit /b 1
)

echo.
echo  =====================================================
echo    ГОТОВО! .exe собран.
echo  =====================================================
echo.
echo  Файл: dist\DayZ Monitor\DayZ Monitor.exe
echo.
echo  Для запуска:
echo    1. Отредактируй config.json (вставь свои токены)
echo    2. Запусти DayZ Monitor.exe
echo.
echo  Для обновления бота на другом компе:
echo    Зипни всю папку "dist\DayZ Monitor" и перекинь
echo.
pause
