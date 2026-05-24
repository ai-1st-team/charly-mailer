# Errors

## 2026-05-23 — Runtime check без зависимостей

Во время проверки импорта `core.proxy_manager` bundled Python не нашёл `requests`.

Причина: зависимости проекта ещё не установлены в проверочном окружении.

Решение: синтаксис проверен через `compileall`; для запуска GUI нужен стандартный шаг `pip install -r requirements.txt`.

## 2026-05-23 — Runtime import AppState без requests

При проверке `core.app_state` в bundled Python снова возник `ModuleNotFoundError: No module named 'requests'`, потому что `AppState` импортирует `ProxyManager`.

Решение: проектный запуск должен идти после `pip install -r requirements.txt`; синтаксис всех файлов проверен через `compileall`.

## 2026-05-23 — GUI падал на `bind_all`

При запуске `main.py` CustomTkinter выбросил:

```text
AttributeError: 'bind_all' is not allowed, could result in undefined behavior
```

Причина: `CTkFrame.bind_all()` запрещён в CustomTkinter. Это было добавлено для события `<<PresetLoaded>>` на вкладках `Setup`, `Content`, `Send`.

Решение: заменено на привязку к root-окну через `self.winfo_toplevel().bind("<<PresetLoaded>>", ..., add="+")`.

Затронуты:

- `gui/tab_setup.py`
- `gui/tab_content.py`
- `gui/tab_send.py`

Проверка: `compileall` прошёл, окно `CHARLY MAILER` запустилось и процесс `python` остался активным.
