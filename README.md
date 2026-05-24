# CHARLY MAILER

Desktop mailer control panel on Python 3.11+ and CustomTkinter.

Current status: Setup has proxy/SMTP loading/checking, Content has subject/body/link/sender-name loading, Campaign has recipient CSV/control inject, Send has test/campaign controls, Stats has real-time metrics/log export.

## Требования

- Python 3.11 или новее
- pip
- Tkinter, обычно входит в стандартный Python для Windows/macOS
- Интернет на первом запуске для установки зависимостей

Проверка:

```powershell
python --version
pip --version
python -c "import tkinter; print('tkinter ok')"
```

Если `python` не найден на Windows, установите Python с https://www.python.org/downloads/ и включите галочку `Add Python to PATH`.

## Быстрый Запуск

### Windows

1. Скачайте или клонируйте проект.
2. Откройте папку проекта.
3. Дважды кликните `start.bat`.

Лаунчер сам выполнит:

```powershell
python -m pip install -r requirements.txt
python main.py
```

Если Python не установлен, окно покажет сообщение `Установите Python с python.org`.

### macOS

1. Скачайте или клонируйте проект.
2. Откройте Terminal в папке проекта.
3. Один раз сделайте лаунчер исполняемым:

```bash
chmod +x start.command
```

4. Запускайте двойным кликом по `start.command` или командой:

```bash
./start.command
```

### Ручной Запуск

Windows PowerShell:

```powershell
cd путь\к\charly-mailer
pip install -r requirements.txt
python main.py
```

macOS/Linux:

```bash
cd /path/to/charly-mailer
python3 -m pip install -r requirements.txt
python3 main.py
```

После запуска должно открыться тёмное окно `CHARLY MAILER` с вкладками `Setup`, `Content`, `Campaign`, `Send`, `Stats`.

## Проверка Установки

Проверить зависимости без запуска GUI:

```powershell
python -c "import customtkinter, requests, dotenv, tkinter; print('OK')"
```

Проверить SMTP-файл без GUI:

```powershell
python test_smtp_login.py data/smtps.txt
```

## Частые Проблемы

`python` не найден:
- переустановите Python 3.11+ с https://www.python.org/downloads/
- на Windows включите `Add Python to PATH`
- закройте и снова откройте терминал

`pip` не найден:

```powershell
python -m ensurepip --upgrade
python -m pip install --upgrade pip
```

`No module named customtkinter`:

```powershell
python -m pip install -r requirements.txt
```

`No module named tkinter`:
- Windows/macOS: переустановите официальный Python с python.org
- Ubuntu/Debian:

```bash
sudo apt install python3-tk
```

## Optional EXE Build

Для будущей передачи без Python можно собрать exe через PyInstaller:

```powershell
pyinstaller --onefile --windowed --name CharlyMailer main.py
```

Structure:
- `main.py` starts the GUI.
- `gui/` contains the main window and five final tabs: Setup, Content, Campaign, Send, Stats.
- `core/` contains business modules for proxy, SMTP, content, queue, sending, stats, and storage helpers.
- `data/` is reserved for private campaign configs and SMTP data.
- `logs/` is reserved for daily JSON campaign logs.
- `memory/` stores project context and decisions as an Obsidian vault.
- `test_smtp_login.py` checks SMTP logins without GUI.

Proxy input formats:
- `http://host:port`
- `http://user:pass@host:port`
- `host:port:user:pass`

SMTP input format:
- `host:port:email:password`

Subject placeholders:
- `{{name}}`
- `{{email}}`
- `{{senderName}}`

Body file format:
- `bodies.txt`
- one body can contain multiple lines
- bodies are separated by `===END===` on its own line
- supports nested spintax like `{one|two {a|b}}`

Link macros:
- `[[LINK]]` uses `links.txt`
- `[[LINK1]]` uses `links1.txt`
- `[[LINK2]]` uses `links2.txt`

Sender names:
- `senders.txt`
- one line is one display name
- From header is `"Name" <smtp_email>` unless email-only mode is enabled

Stats/logs:
- campaign log: `logs/YYYY-MM-DD.json`
- export formats: JSON, CSV
- test-send log: `logs/test-log.json`
- queue resume state: `data/queue-state.json`

Recipients CSV:
- required column: `email`
- optional column: `name`
- extra columns are ignored

Campaign extras:
- CC/BCC addresses are configured on the Campaign tab
- `had_cc` and `had_bcc` are written to campaign logs
- presets are saved as JSON in `data/presets/`
