# Task 07 — Real-time Stats

## Сделано

Добавлена вкладка `Stats` с real-time каркасом статистики кампании.

Пока рассылка не запускается, метрики показывают нули и статус `Остановлено`.

## GUI

На вкладке `Stats` есть:

- верхний прогресс-бар `CTkProgressBar`
- крупная строка статуса: `Остановлено`, `Идёт рассылка: X / Y (Z%)`, `Пауза`, `Завершено`
- блок `Глобальные метрики`
- таблица `SMTP-аккаунты`
- таблица `Прокси`
- выбор формата экспорта `JSON/CSV`
- кнопка `Экспорт лога`

Метрики обновляются через `after(1000, ...)`, поэтому будущий sender сможет писать статистику из фонового потока в `StatsManager`, а GUI будет безопасно читать snapshot.

## Core

`core/stats.py`:

- `StatsManager`
- `get_stats_manager()`
- `StatsSnapshot`
- `GlobalStats`
- `SMTPStats`
- `ProxyStats`
- `LogEntry`
- `append_log_entry()`
- `read_log_records()`
- `export_log()`

## Лог

Дневной лог кампании пишется в:

```text
logs/YYYY-MM-DD.json
```

Файл хранится как валидный JSON-массив объектов.

Запись:

```json
{
  "timestamp": "2026-05-08T14:23:15Z",
  "recipient": "user@example.com",
  "smtp_used": "smtp1@mydomain.com",
  "proxy_used": "1.2.3.4:8080",
  "subject": "...",
  "status": "sent",
  "control": false
}
```

Для ошибок добавляется `error_text`.

## Интеграция с Setup

`gui/tab_setup.py` синхронизирует загруженные/проверенные SMTP и прокси с глобальным `StatsManager`.

Поэтому после загрузки SMTP/прокси на вкладке `Setup` таблицы на `Stats` могут показать эти сущности со счётчиками 0.

## Важно дальше

Когда появится отправка, после каждой попытки отправки вызывать:

```python
get_stats_manager().record_delivery(...)
```

Для старта кампании вызвать:

```python
get_stats_manager().start_campaign(total_recipients)
```
