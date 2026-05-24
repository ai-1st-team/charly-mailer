# Task 09 — Recipients and Control Inject

## Сделано

Добавлена работа с базой получателей и control email инжектом.

## CSV база

Формат:

- CSV с заголовками
- обязательная колонка `email`
- опциональная колонка `name`
- остальные колонки игнорируются

`core/storage.py`:

- `read_recipients_csv()`
- auto-detect delimiter: `,`, `;`, tab
- fallback кодировок уже используется через `read_text_file()`
- пустые email пропускаются
- строки, где `email` начинается с `#`, пропускаются как комментарии
- некорректный email даёт понятную ошибку со строкой
- дубли email в рамках одной загрузки пропускаются

## Проверка

- `compileall` проекта проходит на bundled Python
- parser test: CSV база читает `email/name`, игнорирует комментарии и дубли
- queue test: control email вставляется после каждого N-го письма через `QueueManager`

## GUI

На вкладке `Campaign` добавлено:

- кнопка `Загрузить базу`
- счётчик `загружено N получателей`
- preview первых 5 строк в таблице `email/name`
- поле `Контрольная почта каждые N писем`
- поле `Контрольные адреса`
- статус control-инжекта

## AppState

После загрузки база пишется в:

```python
get_app_state().set_recipients(recipients)
```

Control настройки пишутся в:

```python
get_app_state().control_every
get_app_state().control_recipients
```

## Control inject

При построении очереди `QueueManager.build_from_recipients()`:

- после каждого N-го обычного письма вставляется control-письмо
- control-адреса чередуются по кругу
- `N=0` отключает control-инжект
- control items имеют `control=True`

`core/sender.py`:

- в JSON campaign log уже пишется `"control": true`
- текстовый результат для control писем помечается `[CONTROL]`

## Send integration

Кнопка `▶ СТАРТ РАССЫЛКИ` на вкладке `Send` проверяет `AppState.recipients`.

После загрузки базы на `Campaign` старт становится доступен, если также загружены SMTP, темы и тела.
