@echo off
chcp 65001 >nul
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Установите Python с python.org
    echo.
    pause
    exit /b 1
)

python -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo Не удалось установить зависимости из requirements.txt
    pause
    exit /b 1
)

python main.py
if errorlevel 1 (
    echo.
    echo Приложение завершилось с ошибкой
    pause
)
