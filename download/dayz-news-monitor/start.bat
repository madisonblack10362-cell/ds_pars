@echo off
chcp 65001 >nul
title DayZ News Monitor
color 0A

echo ============================================
echo   DayZ News Monitor - Starting...
echo ============================================
echo.

cd /d "%~dp0"

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

echo.
echo [*] Starting bot...
echo [*] Press Ctrl+C to stop
echo.

python bot.py

:: Если бот упал — не закрываем окно сразу
echo.
echo ============================================
echo   Bot stopped. Press any key to close...
echo ============================================
pause >nul
