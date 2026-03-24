@echo off
echo =============================================
echo   AI Assistant - Instalacao
echo =============================================
echo.

:: Verifica Node.js
where node >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Node.js nao encontrado!
    echo Baixe em: https://nodejs.org
    pause
    exit /b 1
)
echo [OK] Node.js encontrado

:: Verifica Python
where python >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Python nao encontrado!
    echo Baixe em: https://www.python.org/downloads/
    pause
    exit /b 1
)
echo [OK] Python encontrado

echo.
echo --- Instalando dependencias Node.js ---
call npm install
if errorlevel 1 (
    echo [ERRO] Falha ao instalar pacotes Node.js
    pause
    exit /b 1
)
echo [OK] Pacotes Node instalados

echo.
echo --- Instalando dependencias Python ---
pip install -r backend\requirements.txt
if errorlevel 1 (
    echo [ERRO] Falha ao instalar pacotes Python
    pause
    exit /b 1
)
echo [OK] Pacotes Python instalados


echo.
echo =============================================
echo  Instalacao concluida!
echo.
echo  Para iniciar: execute start.bat
echo  Para configurar a API: edite config.json
echo    Campo: ai.api_key
echo =============================================
pause
