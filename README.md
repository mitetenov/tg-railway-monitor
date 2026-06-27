# 🚂 tkt.ge Telegram Ticket Monitor

Telegram-бот для мониторинга наличия железнодорожных билетов на сайте [tkt.ge](https://tkt.ge) (Грузинская железная дорога).

Бот позволяет через Telegram-команды настроить маршрут, дату и класс, после чего автоматически опрашивает API tkt.ge каждые 60 секунд и отправляет уведомление при появлении новых билетов или увеличении свободных мест.

---

## 📋 Содержание

- [Как это работает](#как-это-работает)
- [Команды бота](#команды-бота)
- [Быстрый старт за 5 минут](#быстрый-старт-за-5-минут)
- [Запуск через Docker](#запуск-через-docker)
- [Запуск через systemd](#запуск-через-systemd)
- [Конфигурация (.env)](#конфигурация-env)
- [Структура проекта](#структура-проекта)
- [API tkt.ge](#api-tktge)
- [Разработка](#разработка)
- [Python 3.13 — известная проблема](#python-313--известная-проблема)

---

## Как это работает

```
Telegram User
    │
    ▼  команды (/setroute, /setdate, /setclass)
bot.py ────────────────────► config_manager.py ──► data/{chat_id}.json
    │
    │  при завершении настройки:
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

**Детектируемые изменения:**
- 🆕 **new_ticket** — появился новый класс билетов на рейсе
- 📈 **seats_increased** — увеличилось количество свободных мест в существующем классе

**Технологии:** `python-telegram-bot`, `aiohttp`, `python-dotenv`, `asyncio`.

---

## Команды бота

После запуска бот регистрирует 6 команд:

| Команда | Описание | Пример |
|---------|----------|--------|
| `/start` | Приветствие, отображение текущей конфигурации | `/start` |
| `/setroute` | Выбор станции отправления и прибытия (inline-клавиатура, поиск по страницам) | `/setroute` |
| `/setdate` | Ввод даты поездки. Поддерживает: `today`, `tomorrow`, `+N` (через N дней), `YYYY-MM-DD` | `/setdate tomorrow` |
| `/setclass` | Выбор класса: Any / Business / I / II | `/setclass` |
| `/status` | Текущая конфигурация и статус мониторинга | `/status` |
| `/stop` | Остановка мониторинга для текущего чата | `/stop` |

**Пример диалога настройки маршрута:**

```
User:  /setroute
Bot:   🚉 Выберите станцию отправления:
       [страница 1/3: Tbilisi, Batumi, Kutaisi Airport, ...]
User:  (выбирает Tbilisi)
Bot:   🚉 Выберите станцию прибытия:
User:  (выбирает Batumi)
Bot:   ✅ Маршрут Tbilisi → Batumi сохранён!

User:  /setdate tomorrow
Bot:   ✅ Дата установлена: 2026-06-27

User:  /setclass
Bot:   💺 Выберите класс:
       [Any] [I Class] [II Class] [Business]
User:  (выбирает I Class)
Bot:   ✅ Класс установлен: I Class. Мониторинг запущен!
```

---

## Быстрый старт за 5 минут

### Docker (рекомендуемый способ)

```bash
# 1. Перейдите в директорию проекта
cd /root/tg-ticket-monitor

# 2. Создайте .env из шаблона
cp .env.example .env
nano .env    # вставьте BOT_TOKEN от @BotFather

# 3. Запустите контейнер
docker compose up -d

# 4. Проверьте логи
docker compose logs -f
```

> **Примечание:** Ранее проект использовал systemd для bare-metal запуска. Этот способ считается **устаревшим** — все новые установки должны использовать Docker. Подробнее о миграции — в [DEPLOY.md](DEPLOY.md).

---

## Запуск через Docker

### Требования

- Docker Engine 24+ и Docker Compose v2+

### docker-compose.yml (уже в проекте)

```yaml
services:
  bot:
    build: .
    restart: unless-stopped
    env_file: .env
    environment:
      - ROUTE=${ROUTE:-}   # необязательно, переопределяется командами бота
      - DATE=${DATE:-}
      - CLASS=${CLASS:-}
    volumes:
      - data:/app/data     # персистентность per-chat конфигов
    container_name: tg-ticket-monitor

volumes:
  data:
```

### Команды

```bash
# Сборка и запуск
docker compose up -d

# Просмотр логов
docker compose logs -f

# Остановка
docker compose down

# Пересборка после изменений
docker compose build --no-cache && docker compose up -d
```

### Переменные окружения Docker

Передаются через `.env` файл (автоматически загружается `docker compose`):

| Переменная | Обязательно | Описание |
|-----------|-------------|----------|
| `BOT_TOKEN` | ✅ Да | Токен бота от [@BotFather](https://t.me/BotFather) |
| `ROUTE` | ❌ Нет | Код станции назначения (умолчание) |
| `DATE` | ❌ Нет | Дата поездки (умолчание) |
| `CLASS` | ❌ Нет | Класс (умолчание) |

При запуске **без Docker Compose** (чистый `docker run`):

```bash
docker run -d --restart unless-stopped \
  --name tg-ticket-monitor \
  -e BOT_TOKEN=your_token_here \
  tg-ticket-monitor
```

В этом случае `docker-entrypoint.sh` сам сгенерирует `.env` внутри контейнера.

---

## Запуск через systemd (устаревший способ)

> **⚠️ ВНИМАНИЕ:** Начиная с июня 2026, проект использует **Docker** как основной способ деплоя.
> systemd-запуск считается **legacy** и больше не поддерживается для новых установок.
> Если вы ещё используете systemd — см. [DEPLOY.md](DEPLOY.md) для инструкции по миграции на Docker.

Проект включает готовый unit-файл: `tg-ticket-monitor.service` (хранится в репозитории для истории).

**Установка** (автоматически через `deploy.sh` или вручную):

```bash
# Установить unit
sudo cp tg-ticket-monitor.service /etc/systemd/system/
sudo systemctl daemon-reload

# Создать системного пользователя (если ещё нет)
sudo useradd --system --no-create-home --shell /usr/sbin/nologin tg-ticket-mon

# Настроить права
sudo chown -R tg-ticket-mon:tg-ticket-mon /root/tg-ticket-monitor
sudo chmod 755 /root
sudo chmod 600 /root/tg-ticket-monitor/.env
```

**Параметры сервиса:**

| Параметр | Значение |
|----------|----------|
| Service file | `/etc/systemd/system/tg-ticket-monitor.service` |
| Пользователь | `tg-ticket-mon` (system, no login) |
| Рабочая директория | `/root/tg-ticket-monitor` |
| Python | `.venv/bin/python3` (virtualenv) |
| Файл конфигурации | `/root/tg-ticket-monitor/.env` |
| Данные | `/root/tg-ticket-monitor/data/` (per-chat JSON) |

**Управление сервисом:**

```bash
# Статус
systemctl status tg-ticket-monitor

# Логи
journalctl -u tg-ticket-monitor -f
journalctl -u tg-ticket-monitor -n 50 --no-pager

# Перезапуск
systemctl restart tg-ticket-monitor

# Остановка
systemctl stop tg-ticket-monitor

# Отключение автозапуска
systemctl disable tg-ticket-monitor
```

---

## Конфигурация (.env)

Файл `.env.example` содержит шаблон со всеми переменными:

```ini
# Required:
BOT_TOKEN=your_bot_token_here

# Optional per-chat defaults (overridden at runtime via Telegram commands):
# ROUTE=57151      # destination station code
# DATE=2026-07-01  # travel date (YYYY-MM-DD)
# CLASS=1          # seat class (1 = 1st, 2 = 2nd, 3 = 3rd)
```

Код станции можно узнать:
- из списка популярных станций бота (при `/setroute`)
- через API: `api_explorer.py` (CLI-инструмент)

> **Важно:** файл `.env` НЕ должен попасть в Git — он добавлен в `.gitignore`.

---

## Структура проекта

> Полная информация о каждом модуле, тестах и инфраструктуре — в [structure.md](structure.md).

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
├── tg-ticket-monitor.service    # ⚙️ Unit-файл systemd (legacy, хранится для истории)
├── DEPLOY.md                    # 📖 Документация по деплою (в т.ч. Docker)
├── patch_slots.py               # 🔧 Патч python-telegram-bot для Python 3.13
│
├── README.md                    # 📖 Этот файл
├── api-docs.md                  # 📖 Документация API tkt.ge
├── structure.md                 # 📖 Подробная архитектура проекта
├── .env.example                 # 📋 Шаблон .env
├── .gitignore                   # 🙈 Правила игнорирования Git
├── requirements.txt             # 📦 Python-зависимости
│
├── api_explorer.py              # 🔬 Интерактивный CLI-исследователь API
├── _debug_updater.py            # 🐛 Проверка класса Updater telegram-bot
├── _debug_slots.py              # 🐛 Анализ __slots__ и MRO Updater
│
├── config.json                  # 📄 Пример конфигурации standalone-режима
├── sample_*.json                # 📊 Примеры данных от API tkt.ge
│
├── data/                        # 📁 Per-чатовые JSON-конфиги (gitignored)
│   └── {chat_id}.json
│
└── tests/                       # 🧪 Тесты
    ├── test_api.py
    ├── test_config_manager.py
    ├── test_poller.py
    ├── test_ticket_monitor.py   # Основной файл с тестами
    └── check_syntax.py          # Проверка синтаксиса AST
```

### Основные модули

| Модуль | Назначение |
|--------|-----------|
| `bot.py` | Точка входа. Регистрирует команды Telegram, ConversationHandler'ы (/setroute, /setdate, /setclass). Загружает станции из API при старте. |
| `ticket_monitor.py` | Ядро мониторинга. Класс `TicketMonitor` с фоновым threading-поллером. Без внешних зависимостей — только Python stdlib (`urllib`, `threading`). |
| `api.py` | Асинхронный API-клиент. Три эндпоинта: станции, календарь доступности, список рейсов. Использует `aiohttp`. |
| `poller.py` | Фоновый asyncio-поллер. Управляет per-chat задачами опроса API каждые 60 секунд. Анти-spam через `_notified`. |
| `config_manager.py` | CRUD для per-chat JSON-конфигов в `data/{chat_id}.json`. |

---

## API tkt.ge

Бот использует публичное API [tkt.ge](https://tkt.ge) (Грузинская железная дорога).

**Базовый URL:** `https://gateway.tkt.ge/integrations/api/GeorgianRailway`

**Эндпоинты:**

| Эндпоинт | Описание | Используется в |
|----------|----------|----------------|
| `GET /Dictionaries/civil-stations` | Список станций (латиница) | `bot.py`, `api.py` |
| `GET /Availability/availability-calendar` | Календарь доступности на 30 дней | `api_explorer.py` |
| `GET /Availability/available-rides` | Рейсы с классами, ценами и местами | `poller.py`, `ticket_monitor.py` |
| `GET /Availability/availability-time-table` | Сводка популярных маршрутов | `api_explorer.py` |

> **API-ключ публичный:** `7d8d34d1-e9af-4897-9f0f-5c36c179be77` — вшит в клиентский JS tkt.ge, не является секретом.

Полная документация всех эндпоинтов с примерами ответов — в [api-docs.md](api-docs.md).

---

## Разработка

### Локальный запуск без Docker

```bash
# 1. Создайте виртуальное окружение
python3 -m venv .venv
source .venv/bin/activate

# 2. Установите зависимости
pip install -r requirements.txt

# 3. Примените патч для Python 3.13 (если нужно)
python3 patch_slots.py

# 4. Создайте .env с BOT_TOKEN
cp .env.example .env
nano .env

# 5. Запустите бота
python3 bot.py
```

### Запуск тестов

```bash
# Все тесты
python3 -m pytest tests/ -v

# Конкретный тестовый файл
python3 -m pytest tests/test_ticket_monitor.py -v

# С синтаксической проверкой
python3 tests/check_syntax.py
```

### CLI-исследователь API

```bash
python3 api_explorer.py
```

Интерактивный инструмент для изучения эндпоинтов tkt.ge: станции, популярные маршруты, календарь доступности, рейсы по дате.

---

## Python 3.13 — известная проблема

Бот использует `python-telegram-bot==20.8`, у которого есть несовместимость с Python 3.13:

```
NameError: property __polling_cleanup_cb not found in __slots__
```

Причина: класс `Updater` в PTB 20.8 присваивает `self.__polling_cleanup_cb` в `__init__`, но не включает этот атрибут в `__slots__`.

**Решение:** проект включает `patch_slots.py`, который автоматически добавляет недостающий атрибут в `__slots__` класса `Updater`.

> **Docker** (рекомендуемый способ): образ использует `python:3.11-alpine`, где этой проблемы нет.
>
> **systemd (legacy):** скрипт деплоя (`deploy.sh`) применял патч автоматически. При ручной переустановке зависимостей:

```bash
.venv/bin/python3 patch_slots.py
```


---


## Лицензия

Проект распространяется без лицензионных ограничений. Используйте на свой страх и риск.
