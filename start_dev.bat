@echo off
chcp 65001 >nul
echo =============================================
echo   AI Assistant - Modo Desenvolvimento
echo =============================================
echo.

:: Mata qualquer processo na porta 8765
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8765 "') do (
    taskkill /PID %%a /F >nul 2>&1
)

:: O Electron ja inicia o backend automaticamente (app/main.js)
:: Os logs aparecem com o prefixo [Backend] no terminal
npm run dev
pause
