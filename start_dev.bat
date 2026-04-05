@echo off
chcp 65001 >nul
echo =============================================
echo   AI Assistant - Modo Desenvolvimento
echo =============================================
echo.

:: Ativa conda para que o backend Python use o ambiente correto
call conda activate yara 2>nul || echo [AVISO] Ambiente conda 'yara' nao encontrado, usando Python do sistema.

:: Mata qualquer processo na porta 8765
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8765 "') do (
    taskkill /PID %%a /F >nul 2>&1
)

:: cargo tauri dev compila o Rust, inicia WebView2 com DevTools ativado
cargo tauri dev
pause
