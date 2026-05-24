# CHARLY MAILER

Desktop mailer control panel on Python 3.11+ and CustomTkinter.

Current status: Setup has proxy/SMTP loading/checking, Content has subject/body/link/sender-name loading, Campaign has recipient CSV/control inject, Send has test/campaign controls, Stats has real-time metrics/log export.

## Запуск

Способ 1 — двойной клик:

- Windows: `start.bat`
- macOS: `start.command`

На macOS один раз сделайте файл исполняемым:

```bash
chmod +x start.command
```

Способ 2 — вручную:

```powershell
pip install -r requirements.txt
python main.py
```

Опционально для будущей передачи без Python можно собрать exe через PyInstaller:

```powershell
pyinstaller --onefile --windowed --name CharlyMailer main.py
```

Standalone SMTP check:

```powershell
python test_smtp_login.py data/smtps.txt
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
