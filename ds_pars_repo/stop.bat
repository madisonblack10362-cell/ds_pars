@echo off
chcp 65001 >nul
title DayZ News Monitor - Stop
color 0C

echo ============================================
echo   DayZ News Monitor - Stopping...
echo ============================================
echo.

taskkill /F /IM python.exe 2>nul

if %errorlevel% == 0 (
    echo [*] Bot stopped successfully.
) else (
    echo [!] No running python processes found.
)

echo.
timeout /t 2 >nul
exit
