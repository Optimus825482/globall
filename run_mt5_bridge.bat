@echo off
title SCALPER AGENT - IC MARKETS MT5 BRIDGE
color 0B
echo ==========================================================
echo   SCALPER AGENT GLOBAL - IC MARKETS MT5 CANLI KOPRU
echo ==========================================================
echo MT5 Hesabi : 53077151 (ICMarketsSC-Demo)
echo API Adresi : https://global.erkanerdem.online
echo.

:: Python 3.12 veya varsayilan pythonu bul
set PYTHON_CMD=
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set "PYTHON_CMD=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
) else (
    where py >nul 2>nul
    if %errorlevel% equ 0 (
        set "PYTHON_CMD=py -3.12"
    ) else (
        set "PYTHON_CMD=python"
    )
)

echo [*] Python Calistirici: %PYTHON_CMD%

:: MetaTrader5 kutuphanesini kontrol et
%PYTHON_CMD% -c "import MetaTrader5" >nul 2>nul
if %errorlevel% neq 0 (
    echo [*] MetaTrader5 paketi yukleniyor, lutfen bekleyin...
    %PYTHON_CMD% -m pip install MetaTrader5
)

echo.
echo [*] Kopru baslatiliyor...
%PYTHON_CMD% "%~dp0scripts\mt5_bridge.py"

echo.
echo ==========================================================
echo Kopru sonlandi. Yeniden baslatmak icin bir tusa basin.
pause
