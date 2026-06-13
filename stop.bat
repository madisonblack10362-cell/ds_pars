@echo off
chcp 65001 >nul
title DayZ Monitor - Stop

cd /d "%~dp0"

echo [*] Stopping DayZ News Monitor...

:: Убиваем окно бота по заголовку вместе со всеми дочерними процессами
taskkill /F /FI "WINDOWTITLE eq DayZMonitorBot" /T >nul 2>&1

:: Фоллбэк — ищем процесс по командной строке (src\bot.py)
for /f "tokens=2" %%P in ('wmic process where "commandline like '%%src\\bot.py%%'" get processid /value 2^>nul ^| find "ProcessId"') do (
    taskkill /F /PID %%P /T >nul 2>&1
)

echo [+] Done.
timeout /t 1 >nul
exit