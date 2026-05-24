# Task 10 — Sender Names

## Сделано

Добавлена рандомизация имени отправителя через `senders.txt`.

## Формат

`senders.txt`:

- одна строка — одно имя отправителя
- пустые строки игнорируются
- строки с `#` игнорируются как комментарии

## Core

`core/content.py`:

- добавлен `SenderNameManager`
- добавлен `SenderNameLoadResult`
- загрузка имён через `read_text_lines(ignore_comments=True)`
- случайный выбор имени для каждого письма

`core/app_state.py`:

- общий `sender_name_manager`
- флаг `from_email_only`
- `choose_sender_name()` возвращает случайное имя или пустую строку в email-only режиме

`core/sender.py`:

- `EmailComposer` выбирает sender name один раз на письмо
- это же имя уходит в `{{senderName}}`
- `From` формируется как `"Name" <smtp_email>`
- при email-only режиме `From` содержит только SMTP email

## GUI

На вкладке `Content` добавлен блок `Имена отправителей`:

- кнопка `Загрузить имена отправителей`
- счётчик `загружено N имён`
- preview первых 5 имён
- чекбокс `использовать только email без имени`

## Проверка

- `compileall` проекта проходит
- standalone test: загрузка `senders.txt`, игнор пустых/comment строк
- standalone test: `{{senderName}}` подставляется в тему и тело
