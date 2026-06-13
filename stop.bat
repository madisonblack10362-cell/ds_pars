@echo off
chcp 65001 >nul
title DayZ Monitor - Stop

cd /d "%~dp0"

echo [*] Stopping DayZ News Monitor...

:: Ищем процесс python.exe с src\bot.py в командной строке и убиваем дерево процессов
for /f "tokens=2 delims==" %%P in ('wmic process where "commandline like '%%src\\bot.py%%'" get processid /value 2^>nul ^| find "ProcessId"') do (
    taskkill /F /PID %%P /T >nul 2>&1
    echo [+] Killed PID %%P
)

:: Фоллбэк — по заголовку окна GUI
taskkill /F /FI "WINDOWTITLE eq DayZ News Monitor" /T >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq DayZMonitorBot" /T >nul 2>&1

:: Фоллбэк — все python.exe
taskkill /F /IM python.exe /T >nul 2>&1

echo [+] Done.
timeout /t 1 >nul
exit