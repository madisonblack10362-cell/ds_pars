@echo off
chcp 65001 >nul
title DayZ Monitor - Launcher
color 0A

cd /d "%~dp0"

:: Проверяем config.json
if not exist "config.json" (
    echo [!] config.json не найден!
    echo     Скопируй config.example.json в config.json
    echo     и заполни свои токены.
    echo.
    pause
    exit /b 1
)

:: Проверяем есть ли venv
if not exist "venv\Scripts\activate.bat" (
    echo [!] Virtual environment not found!
    echo     Creating venv...
    python -m venv venv
    call venv\Scripts\activate.bat
    pip install -r requirements.txt
) else (
    call venv\Scripts\activate.bat
)

:: Создаём нужные папки
if not exist "config" mkdir config
if not exist "logs" mkdir logs
if not exist "database" mkdir database
if not exist "images" mkdir images
if not exist "downloads" mkdir downloads

:: Запускаем бота в ОТДЕЛЬНОМ окне с уникальным заголовком
echo [*] Starting bot...
start "DayZMonitorBot" cmd /k "cd /d "%~dp0" && call venv\Scripts\activate.bat && python src\bot.py"

echo [*] Bot started in separate window.
echo [*] Use stop.bat to close it.
timeout /t 2 >nul
exit