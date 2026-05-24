# Task 11 — CC/BCC, Presets, Launchers

## Сделано

Добавлены настройки CC/BCC, JSON-пресеты кампании и лаунчеры для запуска без терминальных команд.

## Campaign GUI

Вкладка `Campaign` теперь скроллится и содержит:

- `База получателей`
- `Control-инжект`
- `Дополнительные получатели`
- `Пресеты кампании`

Блок `Дополнительные получатели`:

- `CC адреса`
- `BCC адреса`
- `Процент писем с CC`
- `Процент писем с BCC`

Адреса вводятся через запятую. Проценты валидируются в диапазоне 0-100.

## Core

`core/app_state.py`:

- `cc_addresses`
- `bcc_addresses`
- `cc_percent`
- `bcc_percent`
- send speed settings для пресетов
- source path для базы получателей

`core/sender.py`:

- `EmailComposer` на каждое письмо независимо решает, добавлять ли CC/BCC
- `RenderedEmail` хранит `cc`, `bcc`, `had_cc`, `had_bcc`
- MIME получает `Cc` и `Bcc`

`core/stats.py`:

- дневной лог пишет `had_cc`
- дневной лог пишет `had_bcc`
- CSV export включает эти поля

## Пресеты

`core/presets.py`:

- `save_preset()`
- `load_preset()`
- хранит пути/URL источников и настройки кампании
- при загрузке очищает runtime, затем перечитывает файлы
- пропавшие файлы дают предупреждения без краша
- сохранение пресета блокируется, если текущие поля Campaign невалидны

Сохраняется:

- proxy files / proxy urls
- SMTP files
- subjects/bodies/link/senders files
- recipients CSV
- control settings
- CC/BCC settings
- speed settings
- `unique_links_per_message`
- `from_email_only`

## Лаунчеры

Созданы:

- `start.bat`
- `start.command`

Оба переходят в папку проекта, ставят зависимости из `requirements.txt` и запускают `main.py`.

`main.py` создаёт при старте:

- `data/`
- `data/presets/`
- `logs/`

## Проверка

- `compileall` проекта проходит
- compose-test проверяет CC/BCC MIME headers и email-only From
