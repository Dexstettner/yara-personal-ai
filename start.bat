@echo off
chcp 65001 >nul
echo =============================================
echo   AI Assistant - Iniciando...
echo =============================================
echo.

:: Ativa conda para que o backend Python use o ambiente correto
call conda activate yara 2>nul || echo [AVISO] Ambiente conda 'yara' nao encontrado, usando Python do sistema.

:: Mata qualquer processo usando a porta 8765
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8765 "') do (
    taskkill /PID %%a /F >nul 2>&1
)

if exist "src-tauri\target\release\yara-personal-ai.exe" (
    src-tauri\target\release\yara-personal-ai.exe
) else (
    echo [INFO] Binario nao encontrado, iniciando em modo desenvolvimento...
    cargo tauri dev
)
pause
