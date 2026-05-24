# Architecture

## Главный поток

`main.py` настраивает CustomTkinter и запускает `gui.window.MainWindow`.

GUI работает в основном потоке. Все долгие операции в следующих задачах должны запускаться через `threading`, чтобы окно не зависало.

## GUI

`gui/window.py` создаёт главное окно:

- title: `CHARLY MAILER`
- size: `900x600`
- theme: dark
- brand colors:
  - background: `#0a0a0a`
  - accent: `#4ade80`
  - error: `#ef4444`
  - warning: `#fbbf24`

Финальный набор вкладок зафиксирован:

1. `Setup` — прокси и SMTP-аккаунты; сейчас реализованы блоки прокси и SMTP
2. `Content` — темы, тела писем, ссылки, имена отправителей; сейчас реализованы блоки тем, имён отправителей, ссылок и тел
3. `Campaign` — база получателей, control-инжект, CC/BCC; сейчас реализованы база, control-инжект, CC/BCC и пресеты
4. `Send` — тест и управление массовой рассылкой; сейчас реализована отправка теста и campaign controller
5. `Stats` — статистика и прогресс; сейчас реализована real-time вкладка статистики

Модули вкладок:

- `gui/tab_setup.py`
- `gui/tab_content.py`
- `gui/tab_campaign.py`
- `gui/tab_send.py`
- `gui/tab_stats.py`

Модуль `gui/tab_setup.py` сейчас содержит блок прокси и блок SMTP.
Модуль `gui/tab_content.py` сейчас содержит блок тем писем, блок имён отправителей, блок ссылок и блок тел писем.
Модуль `gui/tab_campaign.py` сейчас содержит загрузку базы, control-инжект, CC/BCC и пресеты.
Модуль `gui/tab_stats.py` сейчас содержит прогресс, метрики, таблицы SMTP/прокси и экспорт логов.
Модуль `gui/tab_send.py` сейчас содержит тестовую отправку, preview, start/stop/pause и настройки скорости.
## Core

- `core/proxy_manager.py` — прокси: загрузка из файла/URL, парсинг, проверка, исключение мёртвых, round-robin ротация живых
- `core/smtp_manager.py` — SMTP: загрузка аккаунтов, login-check, шифрование по порту, session-счётчики, round-robin живых аккаунтов
- `core/content.py` — темы, тела, имена отправителей, link-макросы, placeholder rendering, вложенный спинтакс, plain/html detection
- `core/queue_manager.py` — очередь получателей и состояние кампании
- `core/sender.py` — composition, MIME, test send, campaign worker
- `core/stats.py` — статистика, прогресс, агрегаты, дневной JSON-лог, экспорт JSON/CSV
- `core/storage.py` — общие helpers чтения TXT/CSV, игнор пустых строк, опционально игнор строк с `#`
- `core/app_state.py` — общий state приложения для всех вкладок
- `core/presets.py` — сохранение и загрузка JSON-пресетов кампании

## Proxy flow

1. GUI вызывает `ProxyManager.load_from_file()` или `ProxyManager.load_from_url()`.
2. `storage.py` чистит строки: пропускает пустые и строки, начинающиеся с `#`.
3. `proxy_manager.py` парсит строки в `ProxyRecord`.
4. Повторная загрузка из того же источника заменяет старые прокси этого источника.
5. `ProxyManager.check_all()` проверяет каждый прокси через `http://httpbin.org/ip`.
6. Живые получают статус `alive`, мёртвые — `dead`.
7. Для будущей рассылки `prepare_live_rotation()` перепроверяет список и возвращает только `alive`.

## SMTP flow

1. GUI вызывает `SMTPManager.load_from_file()` для `smtps.txt`.
2. `storage.py` пропускает пустые строки и строки, начинающиеся с `#`.
3. `smtp_manager.py` парсит строки в `SMTPAccount`.
4. Повторная загрузка из того же файла заменяет старые аккаунты этого источника.
5. `SMTPManager.check_account()` проверяет login через `smtplib`.
6. Шифрование определяется по порту: `465` SSL, `587` STARTTLS, `25` opportunistic STARTTLS.
7. `SMTPManager.get_next_live_account()` отдаёт живые аккаунты round-robin.
8. `record_send_success()` увеличивает session-счётчик отправленных писем.

## Subject flow

1. GUI вызывает `SubjectManager.load_from_file()` для `subjects.txt`.
2. `storage.py` пропускает пустые строки, но не пропускает строки с `#`.
3. `SubjectManager.preview(5)` отдаёт первые пять тем для GUI.
4. Для каждого будущего письма `SubjectManager.render_random()` случайно выбирает тему и подставляет `{{name}}`, `{{email}}`, `{{senderName}}`.

## Body flow

1. GUI вызывает `BodyManager.load_from_file()` для `bodies.txt`.
2. `storage.py` читает файл целиком, сохраняя переносы строк.
3. `split_bodies()` разделяет тела по строке `===END===`.
4. Для каждого будущего письма `BodyManager.render_random()` случайно выбирает тело.
5. `render_spintax()` разворачивает вложенный спинтакс.
6. `render_placeholders()` подставляет `{{name}}`, `{{email}}`, `{{senderName}}`.
7. `detect_body_format()` определяет `plain` или `html`.

## Link flow

1. GUI вызывает `LinkManager.load_from_files()` для выбранных `links*.txt`.
2. Имя файла определяет макрос: `links.txt` → `[[LINK]]`, `links1.txt` → `[[LINK1]]`.
3. Для одного письма создаётся `LinkRenderContext`.
4. Тема и тело рендерятся с одним и тем же `LinkRenderContext`.
5. `LinkManager.render_macros()` заменяет все `[[LINK...]]` случайными ссылками.
6. Если включены уникальные ссылки, context запоминает уже выданные ссылки по каждому списку.

## Sender name flow

1. GUI вызывает `AppState.load_sender_names_from_file()` для `senders.txt`.
2. `SenderNameManager` читает имена через `storage.read_text_lines(ignore_comments=True)`.
3. Для каждого письма `EmailComposer` выбирает одно случайное имя через `AppState.choose_sender_name()`.
4. То же имя передаётся в `{{senderName}}` при рендере темы и тела.
5. MIME `From` формируется как `"Name" <smtp_email>`.
6. Если включён `from_email_only`, имя не выбирается, `{{senderName}}` становится пустым, а `From` содержит только SMTP email.

## Stats flow

1. GUI вкладка `Stats` читает `get_stats_manager().snapshot()` раз в секунду через `after()`.
2. Будущий sender вызывает `start_campaign(total_recipients)` при запуске.
3. После каждой попытки отправки sender вызывает `record_delivery(...)`.
4. `StatsManager` обновляет глобальные счётчики, SMTP/proxy counters и пишет `logs/YYYY-MM-DD.json`.
5. Экспорт работает через `export_log(destination, "json" | "csv")`.

## Send flow

1. `Send` читает настройки из общего `AppState`.
2. `EmailComposer` выбирает sender name, рендерит тему, тело, ссылки и MIME.
3. `EmailDeliveryService.send_test()` отправляет одиночное письмо и пишет `logs/test-log.json`.
4. `CampaignController.start_new()` строит очередь через `QueueManager`.
5. Фоновый thread отправляет письма по очереди, уважает pause/stop и задержки.
6. После каждой попытки обновляется `StatsManager` и `data/queue-state.json`.

## Campaign flow

1. GUI вызывает `read_recipients_csv()` для выбранного CSV.
2. CSV обязан иметь колонку `email`, колонка `name` опциональна.
3. Получатели пишутся в `AppState.recipients`.
4. Control settings пишутся в `AppState.control_every` и `AppState.control_recipients`.
5. `QueueManager.build_from_recipients()` вставляет control recipients при старте отправки.

## CC/BCC flow

1. `Campaign` парсит CC/BCC адреса через запятую и проценты 0-100.
2. Настройки сохраняются в `AppState.cc_addresses`, `bcc_addresses`, `cc_percent`, `bcc_percent`.
3. `EmailComposer.compose()` для каждого письма независимо решает, добавлять ли CC и BCC.
4. MIME получает `Cc` и `Bcc`; `smtplib.send_message()` использует BCC как envelope recipients без раскрытия в письме.
5. `StatsManager.record_delivery()` пишет `had_cc` и `had_bcc` в дневной JSON/CSV лог.

## Preset flow

1. `Campaign` вызывает `save_preset()` или `load_preset()` из `core.presets`.
2. Пресет хранит пути/URL источников: proxy, SMTP, subjects, bodies, links, senders, recipients.
3. Также хранит `control`, `additional_recipients`, `send_settings`, `unique_links_per_message`, `from_email_only`.
4. При загрузке пресета runtime очищается, затем файлы перечитываются менеджерами.
5. Если файл не найден, GUI получает предупреждение, но не падает.
6. После загрузки генерируется событие `<<PresetLoaded>>`, вкладки обновляют свои списки и поля.

## Runtime folders

- `data/` — приватные конфиги и данные рассылки; содержимое исключено из git, кроме `.gitkeep`
- `logs/` — JSON-логи кампаний по дням; содержимое исключено из git, кроме `.gitkeep`
- `memory/` — Obsidian vault с контекстом проекта
- `data/presets/` — пользовательские JSON-пресеты, создаётся автоматически
