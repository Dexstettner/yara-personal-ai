@echo off
chcp 65001 >nul
echo =============================================
echo   AI Assistant - Docker Dev Mode
echo =============================================
echo.

:: Verifica se Docker está rodando
docker info >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Docker nao esta rodando. Inicie o Docker Desktop e tente novamente.
    pause
    exit /b 1
)

:: IMPORTANTE: Ollama deve estar acessivel em localhost:11434 no host.
:: O container acessa via host.docker.internal:11434 — verifique config.json:
::   "base_url": "http://host.docker.internal:11434"

echo [Docker] Build e inicializando backend...
docker compose up -d --build
if errorlevel 1 (
    echo [ERRO] Falha ao iniciar container. Verifique os logs: docker compose logs
    pause
    exit /b 1
)

:: Aguarda o health check do backend
echo [Docker] Aguardando backend ficar pronto...
set /a tentativas=0
:loop_health
set /a tentativas+=1
if %tentativas% gtr 30 (
    echo [ERRO] Backend nao respondeu apos 30s. Logs:
    docker compose logs --tail=30
    pause
    exit /b 1
)
docker inspect --format="{{.State.Health.Status}}" yara-backend 2>nul | findstr /i "healthy" >nul
if errorlevel 1 (
    timeout /t 2 >nul
    goto loop_health
)
echo [Docker] Backend pronto.
echo.

:: Mata qualquer processo na porta 8765 do host (nao mais necessario, mas por segurança)
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8765 "') do (
    taskkill /PID %%a /F >nul 2>&1
)

:: Inicia Electron apontando para o backend Docker (sem spawnar Python)
echo [Electron] Iniciando frontend...
set EXTERNAL_BACKEND=1
npm run dev

:: Ao fechar o Electron, para o container
echo.
echo [Docker] Encerrando backend...
docker compose down
