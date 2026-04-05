@echo off
chcp 65001 >nul
echo =============================================
echo   AI Assistant - Instalacao (Tauri/Rust)
echo =============================================
echo.

:: Verifica Rust/Cargo
where cargo >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Rust/Cargo nao encontrado!
    echo Instale em: https://rustup.rs/
    pause
    exit /b 1
)
echo [OK] Rust/Cargo encontrado

:: Instala Tauri CLI (necessario para cargo tauri dev / build)
echo.
echo --- Instalando Tauri CLI ---
cargo install tauri-cli --version "^2" --locked
if errorlevel 1 (
    echo [AVISO] Falha ao instalar tauri-cli (pode ja estar instalado)
)
echo [OK] Tauri CLI verificado

:: Instala dependencias Python do backend
echo.
echo --- Instalando dependencias do backend Python ---
where conda >nul 2>&1
if not errorlevel 1 (
    call conda activate yara 2>nul
)
pip install -r backend\requirements\base.txt
if errorlevel 1 (
    echo [ERRO] Falha ao instalar pacotes do backend
    pause
    exit /b 1
)
echo [OK] Pacotes do backend instalados

echo.
echo =============================================
echo  Instalacao concluida!
echo.
echo  Para iniciar (dev):  execute start_dev.bat
echo  Para compilar prod:  cargo tauri build
echo  Para configurar:     edite config.json
echo =============================================
pause
