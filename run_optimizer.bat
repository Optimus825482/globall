@echo off
REM VectorBT Optimizer Calistirici (Otomatik Sanal Ortam ile)
cd /d "%~dp0"
if exist "backend\venv\Scripts\python.exe" (
    backend\venv\Scripts\python.exe scripts\vectorbt_optimizer.py %*
) else (
    python scripts\vectorbt_optimizer.py %*
)
