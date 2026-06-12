@echo off
chcp 65001 >nul
title DayZ News Monitor - Stop
color 0C

echo ============================================
echo   DayZ News Monitor - Stopping...
echo ============================================
echo.

cd /d "%~dp0"

:: Ищем процесс по командной строке (src\bot.py)
for /f "tokens=2" %%P in ('wmic process where "commandline like '%%src\\bot.py%%'" get processid /value 2^>nul ^| find "ProcessId"') do (
    taskkill /F /PID %%P >nul 2>&1
    echo [*] Bot stopped (PID %%P).
    goto :done
)

:: Fallback: пробуем по заголовку окна
tasklist /FI "WINDOWTITLE eq DayZ News Monitor" 2>nul | find /I "python" >nul
if not errorlevel 1 (
    taskkill /F /FI "WINDOWTITLE eq DayZ News Monitor" >nul 2>&1
    echo [*] Bot stopped.
    goto :done
)

echo [!] Бот не запущен.

:done
echo.
timeout /t 2 >nul
exit