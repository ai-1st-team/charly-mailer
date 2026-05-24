#!/bin/sh

cd "$(dirname "$0")" || exit 1

if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
else
    echo "Установите Python с python.org"
    read -r _
    exit 1
fi

"$PYTHON_BIN" -m pip install -r requirements.txt || {
    echo "Не удалось установить зависимости из requirements.txt"
    read -r _
    exit 1
}

"$PYTHON_BIN" main.py || {
    echo "Приложение завершилось с ошибкой"
    read -r _
    exit 1
}
