# Структура проекта `tg-ticket-monitor`

**Назначение:** Telegram-бот для мониторинга наличия железнодорожных билетов на сайте tkt.ge (Грузинская железная дорога). Бот позволяет через Telegram-команды настроить маршрут, дату и класс, после чего автоматически опрашивает API и отправляет уведомления при появлении новых билетов или увеличении свободных мест.

---

## Корень проекта `/root/tg-ticket-monitor`

```
tg-ticket-monitor/
├── bot.py                       # ⚡ Точка входа — Telegram-бот
├── ticket_monitor.py            # 🧠 Ядро: опрос API + diff состояний + нотификации
├── api.py                       # 📡 Асинхронный клиент API tkt.ge
├── poller.py                    # 🔄 Фоновый asyncio-поллер (по одному на чат)
├── config_manager.py            # ⚙️ Управление конфигурацией чатов (JSON)
│
├── Dockerfile                   # 🐳 Образ Docker (python:3-alpine)
├── docker-compose.yml           # 🐳 Docker Compose с volume data/
├── docker-entrypoint.sh         # 🏁 Генерация .env из переменных окружения
├── deploy.sh                    # 🚀 Deploy-скрипт (устаревший — systemd legacy)
├── tg-ticket-monitor.service    # ⚙️ Unit-файл systemd (legacy)
├── DEPLOY.md                    # 📖 Документация по деплою (рекомендуется Docker)
├── config.json                  # 📄 Пример конфигурации для standalone-режима
├── monitor_state.json           # 💾 Сохранённое состояние (gitignored)
├── requirements.txt             # 📦 Python-зависимости
├── .env                         # 🔑 Секреты (gitignored, BOT_TOKEN)
├── .env.example                 # 📋 Шаблон .env
├── .gitignore                   # 🙈 Правила игнорирования Git
│
├── api_explorer.py              # 🔬 Интерактивный CLI-исследователь API
├── _debug_updater.py            # 🐛 Проверка класса Updater telegram-bot
├── _debug_slots.py              # 🐛 Анализ __slots__ и MRO Updater
├── verify_imports.py            # 🗑️ Пустой файл-маркер (можно удалить)
│
├── data/                        # 📁 Пер-чатовые JSON-конфиги (gitignored)
│   └── {chat_id}.json
│
├── tests/                       # 🧪 Тесты
│   ├── test_api.py
│   ├── test_config_manager.py
│   ├── test_poller.py
│   ├── test_ticket_monitor.py   # Основной файл с тестами
│   └── check_syntax.py          # Проверка синтаксиса AST
│
├── sample_*.json                # 📊 Примеры данных от API tkt.ge
│
├── .venv/                       # 🐍 Виртуальное окружение Python (gitignored)
└── .git/                        # 📂 Git-репозиторий
```

---

## 1. Основные модули

### `bot.py` — Точка входа и Telegram-интерфейс
- **Роль:** Запускает `python-telegram-bot` Application, регистрирует команды и ConversationHandler'ы.
- **Команды:**
  - `/start` — приветствие, отображение текущей конфигурации
  - `/setroute` — выбор станций отправления и прибытия (постраничный inline-клавиатурой)
  - `/setdate` — ввод даты поездки (поддерживает `today`, `tomorrow`, `+N`, `YYYY-MM-DD`)
  - `/setclass` — выбор класса (Any / Business / I / II)
  - `/status` — текущая конфигурация и статус мониторинга
  - `/stop` — остановка мониторинга
- **Состояния ConversationHandler:** `FROM_STATION`, `TO_STATION`, `WAITING_DATE`, `WAITING_CLASS`
- **Особенности:**
  - Загружает станции из API при старте (с fallback-списком из 17 популярных станций)
  - При завершении конфигурации автоматически запускает поллер через `poller.start()`
  - Fallback-обработчик для неизвестных команд

### `ticket_monitor.py` — Ядро мониторинга
- **Роль:** Независимый класс `TicketMonitor` с фоновым threading-поллером. Не имеет внешних зависимостей — использует только Python stdlib (`urllib`, `threading`, `json`).
- **Классы:**
  - `RouteConfig` — dataclass с настройками маршрута (коды станций, дата, фильтр класса, кол-во пассажиров). Автозаполняет названия станций и дату по умолчанию (завтра).
  - `TicketState` — сериализуемый снимок известных билетов `{route_key: {ride_num: {class_id: {seats, price}}}}`.
  - `TicketMonitor` — основной класс с методами `start()`, `stop()`, `poll_once()`, `on_change()`.
- **Детектируемые изменения:** `new_ticket` (новый класс билетов) и `seats_increased` (увеличилось число мест).
- **Форматирование:** Готовое Telegram-сообщение с маркдауном, эмодзи и деталями рейса.
- **Публичный API ключ:** `7d8d34d1-e9af-4897-9f0f-5c36c179be77` (встроен в клиентский JS tkt.ge, не является секретом).

### `api.py` — Асинхронный API-клиент
- **Роль:** Асинхронные обёртки (`aiohttp`) для трёх эндпоинтов tkt.ge.
- **Функции:**
  - `get_stations(session)` — получение списка станций
  - `get_available_rides(session, from_code, to_code, date_str, passengers=1)` — рейсы на дату
  - `get_availability_calendar(session, from_code, to_code)` — календарь доступности на 30 дней
  - `fetch_json(session, url, label)` — вспомогательная утилита
- **Базовый URL:** `https://gateway.tkt.ge/integrations/api/GeorgianRailway`

### `poller.py` — Фоновый asyncio-поллер
- **Роль:** Управление per-chat задачами опроса API. Создаёт асинхронную задачу для каждого чата, проверяет билеты каждые 60 секунд.
- **Функции модуля:**
  - `start(bot, chat_id)` — запуск/перезапуск поллера для чата
  - `stop(chat_id)` — остановка поллера для чата
  - `is_running(chat_id)` — проверка активности поллера
  - `active_count()` — кол-во активных мониторов
- **Анти-spam:** Ведёт `_notified` — отслеживает уже отправленные уведомления по комбинации `rideNumber:className`.

### `config_manager.py` — Управление конфигурацией
- **Роль:** CRUD для per-chat JSON-конфигов в `data/{chat_id}.json`.
- **Функции:** `load_config()`, `save_config()`, `delete_config()`, `is_config_complete()`.

---

## 2. Инфраструктура и деплой

### `Dockerfile`
- **Базовый образ:** `python:3-alpine`
- **Установка:** `tzdata` для часовых поясов, pip-зависимости из `requirements.txt`
- **Пользователь:** Непривилегированный `monitor`
- **Точка входа:** `docker-entrypoint.sh` → генерирует `.env`, запускает `bot.py`

### `docker-compose.yml`
- **Сервис:** `bot` (build: `.`), `restart: unless-stopped`
- **Переменные окружения:** Из `.env` + опциональные `ROUTE`, `DATE`, `CLASS`
- **Volume:** `data:/app/data` для сохранения конфигов между перезапусками

### `deploy.sh`
- Создаёт системного пользователя `tg-ticket-mon`
- Настраивает права доступа
- Устанавливает systemd-сервис

### `tg-ticket-monitor.service`
- **Пользователь:** `tg-ticket-mon`
- **Рабочая директория:** `/root/tg-ticket-monitor`
- **Команда:** `.venv/bin/python3 bot.py`
- **Безопасность:** `NoNewPrivileges=true`, `PrivateTmp=true`, `ProtectSystem=full`, `ProtectHome=read-only`
- **Чтение/запись:** только `/root/tg-ticket-monitor/data`

---

## 3. Диагностические скрипты

| Файл | Назначение |
|---|---|
| `api_explorer.py` | CLI-инструмент для исследования API tkt.ge: станции, популярные маршруты, календарь, рейсы |
| `_debug_updater.py` | Просмотр исходного кода `Updater.__init__` из telegram-bot |
| `_debug_slots.py` | Анализ `__slots__` и MRO иерархии классов `Updater` |
| `verify_imports.py` | Пустой маркер |

---

## 4. Тесты (`tests/`)

| Файл | Тип | Описание |
|---|---|---|
| `test_ticket_monitor.py` | unittest | **Основной тестовый файл** (406 строк). Тестирует: RouteConfig (автозаполнение), форматирование сообщений, diff состояний (first poll, no changes, seats increased, API failure, class filter), загрузку конфигов, state save/load, live API integration, background thread start/stop, on_change callback |
| `test_config_manager.py` | pytest | CRUD конфигов, Unicode, проверка полноты конфига |
| `test_api.py` | pytest | Константы API, сигнатуры функций |
| `test_poller.py` | pytest | Формат ключа уведомлений, start/stop без краша |
| `check_syntax.py` | Скрипт | AST-проверка синтаксиса всех модулей |

---

## 5. Данные и примеры

| Файл | Описание |
|---|---|
| `data/{chat_id}.json` | Per-чатовые конфигурации (автоматически, gitignored) |
| `monitor_state.json` | Сохранённое состояние `TicketMonitor` (автоматически, gitignored) |
| `config.json` | Пример конфигурации (Tbilisi ↔ Batumi, 2026-06-27) |
| `sample_availability_today.json` | Пример ответа API available-rides (сегодня) |
| `sample_availability_tomorrow.json` | Пример ответа API available-rides (завтра) |
| `sample_calendar.json` | Пример ответа API availability-calendar |
| `sample_rides.json` | Пример ответа API available-rides |
| `sample_stations.json` | Пример ответа API civil-stations |

---

## 6. Зависимости

Указаны в `requirements.txt`:
- `python-telegram-bot >=20.0,<21.0` — Telegram Bot API
- `aiohttp >=3.9,<4.0` — Асинхронный HTTP-клиент
- `python-dotenv >=1.0` — Загрузка `.env`

---

## 7. Поток данных (Data Flow)

```
Telegram User
    │
    ▼  команды (/setroute, /setdate, /setclass)
bot.py ────────────────────► config_manager.py ──► data/{chat_id}.json
    │
    │  при завершении конфигурации:
    └─► poller.start()
            │
            ▼  каждые 60 секунд
        poller._check_and_notify()
            │
            ├─► api.get_available_rides() ──► tkt.ge API
            │
            └─► при новых билетах:
                    └─► bot.send_message() ──► Telegram User
```

Альтернативный поток (standalone `TicketMonitor`, не через бота):
```
ticket_monitor.TicketMonitor
    │
    ├─► start()  ──► _poll_loop() (threading)
    │
    └─► poll_once()
            ├─► _fetch_rides()  ──► urllib ──► tkt.ge API
            ├─► diff с _state.routes
            └─► on_change callbacks
```
