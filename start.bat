@echo off
echo =============================================
echo   AI Assistant - Iniciando...
echo =============================================
echo.

:: Mata qualquer processo usando a porta 8765
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8765 "') do (
    taskkill /PID %%a /F >nul 2>&1
)

npm start
pause
