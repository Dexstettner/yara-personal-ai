@echo off
chcp 65001 >nul
echo =============================================
echo   KokoClone TTS Server
echo =============================================
echo.

call conda activate kokoclone 2>nul || (
    echo [ERRO] Ambiente conda 'kokoclone' nao encontrado.
    echo Crie com:
    echo   conda create -n kokoclone python=3.12
    echo   conda activate kokoclone
    echo   pip install git+https://github.com/frothywater/kanade-tokenizer.git
    echo   pip install git+https://github.com/Ashish-Patnaik/kokoclone.git
    echo   pip install fastapi uvicorn soundfile
    pause
    exit /b 1
)

python kokoclone/server.py %*
pause
