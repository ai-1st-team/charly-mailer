# Task 08 — Send Flow

## Сделано

Связаны ранее созданные core-модули в рабочий цикл формирования и отправки письма.

Добавлены:

- общий `AppState`
- persistent queue state
- email composer
- test send
- campaign controller
- GUI вкладки `Send`

## AppState

`core/app_state.py` хранит общие менеджеры:

- `ProxyManager`
- `SMTPManager`
- `SubjectManager`
- `BodyManager`
- `LinkManager`
- `QueueManager`
- `StatsManager`
- будущую базу `recipients`
- будущие `sender_names`
- настройку `unique_links_per_message`

`Setup`, `Content` и `Send` теперь работают с одним и тем же state.

## Test Send

На вкладке `Send` добавлен блок:

- поле `Тестовый адрес`
- кнопка `ТЕСТ`
- строка результата

По нажатию:

1. берётся первый живой SMTP
2. если SMTP не проверены, запускается проверка
3. выбирается случайный живой прокси, если прокси есть
4. собирается MIME-письмо с UTF-8
5. отправляется тест
6. результат пишется в `logs/test-log.json`

Тестовая отправка не пишет основной campaign log и не меняет статистику кампании.

## Preview

Кнопка `👁 Превью письма` собирает один полный экземпляр:

- From
- To
- Subject
- Format
- body

Preview использует текущие темы, тела, ссылки и sender name fallback.

Если `senders.txt` ещё не загружен, sender name берётся из email SMTP-аккаунта. Полноценная загрузка имён будет в задаче 10.

## Campaign Controls

На вкладке `Send` добавлены:

- `▶ СТАРТ РАССЫЛКИ`
- `■ СТОП`
- `⏸ ПАУЗА / ▶ ПРОДОЛЖИТЬ`
- `Задержка между письмами (сек)`
- `Писем в минуту`
- `Случайный разброс задержки ±сек`

СТАРТ сейчас disabled, пока нет базы получателей из будущей задачи 09.

Если база появится в `AppState.recipients`, старт будет использовать её без переписывания Send.

## Queue Resume

`core/queue_manager.py` сохраняет прогресс в:

```text
data/queue-state.json
```

Сохраняется:

- индекс текущей позиции
- total
- items
- metadata с настройками кампании

На вкладке `Send` есть блок восстановления:

- если найдена незавершённая очередь, показывается `отправлено N из M`
- кнопка `Продолжить`
- кнопка `Начать заново`

## Campaign Send

`core/sender.py`:

- `EmailComposer`
- `EmailDeliveryService`
- `CampaignController`
- `CampaignSettings`
- `RenderedEmail`
- `SendResult`

При массовой отправке:

1. перед стартом проверяются SMTP и прокси
2. очередь берётся из `QueueManager`
3. SMTP ротируется round-robin через `SMTPManager.get_next_live_account()`
4. прокси ротируется через `ProxyManager.get_next_live_proxy()`
5. после каждой попытки вызывается `StatsManager.record_delivery()`
6. основной лог пишется в `logs/YYYY-MM-DD.json`
7. прогресс очереди сохраняется после каждого письма

## Важно дальше

Задача 09 должна загрузить базу получателей и записывать её в:

```python
get_app_state().set_recipients(recipients)
```

После этого кнопка `▶ СТАРТ РАССЫЛКИ` станет доступна при наличии SMTP, тем и тел.
