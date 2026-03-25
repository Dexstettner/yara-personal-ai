@echo off
chcp 65001 >nul
echo =============================================
echo   AI Assistant - Iniciando...
echo =============================================
echo.

:: Ativa ambiente conda com Python 3.11 (requerido pelo IndexTTS2 / numba)
call conda activate yara 2>nul || echo [AVISO] Ambiente conda 'yara' nao encontrado, usando Python do sistema.

:: Mata qualquer processo usando a porta 8765
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8765 "') do (
    taskkill /PID %%a /F >nul 2>&1
)

npm start
pause
