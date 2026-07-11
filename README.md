# 🚂 tre.ge Telegram Ticket Monitor

Telegram-бот для мониторинга наличия железнодорожных билетов на сайте [tre.ge](https://tre.ge) (Грузинская железная дорога).

Бот позволяет через мастер настройки `/start` выбрать маршрут, дату и класс, после чего автоматически опрашивает API tre.ge каждые 60 секунд и отправляет уведомление при появлении новых билетов или увеличении свободных мест. Поддерживает русский и английский интерфейс с автоопределением языка из профиля Telegram.

---

## 📋 Содержание

- [Как это работает](#как-это-работает)
- [Команды бота](#команды-бота)
- [Язык интерфейса](#язык-интерфейса)
- [Быстрый старт за 5 минут](#быстрый-старт-за-5-минут)
- [Запуск через Docker](#запуск-через-docker)
- [Конфигурация (.env)](#конфигурация-env)
- [Структура проекта](#структура-проекта)
- [API tre.ge](#api-trege)
- [Разработка](#разработка)
- [Python 3.13 — известная проблема](#python-313--известная-проблема)

---

## Как это работает

```
Telegram User
    │
    ▼  /start (wizard с inline-клавиатурами)
bot.py ────────────────────► config_manager.py ──► data/{chat_id}.json
    │
    │  /lang (inline-клавиатура выбора языка)
    │       │
    │  i18n.py ◄─────────── (автоопределение языка из профиля Telegram)
    │
    │  при завершении мастера:
    └─► poller.start()
            │
            ▼  каждые 60 секунд
        poller._check_and_notify()
            │
            ├─► api.get_available_rides()
            │   └─► api_tre.TreGeApi ──► tre.ge API
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

После запуска бот регистрирует 3 команды в меню Telegram:

| Команда | Описание | Пример |
|---------|----------|--------|
| `/start` | Запуск мастера настройки мониторинга (дата → отправление → прибытие → класс) | `/start` |
| `/stop` | Остановка мониторинга и очистка конфигурации для текущего чата | `/stop` |
| `/lang` | Выбор языка интерфейса (inline-клавиатура: 🇬🇧 English / 🇷🇺 Русский) | `/lang` |

### Мастер настройки (`/start`)

Команда `/start` запускает пошаговый мастер с inline-клавиатурами:

1. **Выбор даты:** [Today] [Tomorrow] [Custom date...]
2. **Станция отправления:** [Tbilisi] [Batumi] [All stations...]
3. **Станция прибытия:** [Batumi] [Kutaisi] [All stations...]
4. **Класс билета:** [Any] [I Class] [II Class] [Business]

После выбора класса мониторинг запускается автоматически.

**Пример диалога:**

```
User:  /start
Bot:   📅 Выберите дату поездки:
       [Today] [Tomorrow] [Custom date...]

User:  (нажимает Today)
Bot:   📅 Дата установлена: 2026-07-11
       🚉 Выберите станцию отправления:
       [Tbilisi] [Batumi] [All stations...]

User:  (выбирает Tbilisi)
Bot:   🚉 Станция отправления: Тбилиси
       Выберите станцию прибытия:
       [Batumi] [Kutaisi] [All stations...]

User:  (выбирает Batumi)
Bot:   💺 Выберите класс билета:
       [Any] [I Class] [II Class] [Business]

User:  (выбирает I Class)
Bot:   ✅ Маршрут: Тбилиси → Батуми, 2026-07-11
       Класс: I Class. Мониторинг запущен!
```

> **Примечание:** При повторном вызове `/start` предыдущая конфигурация и состояние мастера сбрасываются, и процесс начинается заново.

### Остановка мониторинга (`/stop`)

Команда `/stop` останавливает фоновый поллер для текущего чата, удаляет конфигурацию (маршрут, дата, класс) и сбрасывает состояние отслеживания. Языковые настройки при этом сохраняются.

---

## Язык интерфейса

Бот поддерживает русский и английский интерфейс.

### Автоопределение

При первом обращении язык определяется автоматически из языковых настроек профиля Telegram (`user.language_code`). Предпочтение сохраняется в per-user конфигурации и используется при всех последующих взаимодействиях.

### Ручной выбор (`/lang`)

```
User:  /lang
Bot:   Выберите язык / Select language:
       [🇬🇧 English] [🇷🇺 Русский]

User:  (нажимает 🇷🇺 Русский)
Bot:   ✅ Язык изменён на Русский
```

Команда `/lang` без аргументов показывает inline-клавиатуру. Также поддерживается прямой вызов:

```
/lang en   — переключить на английский
/lang ru   — переключить на русский
```

### Станции на двух языках

Названия станций (Тбилиси/Tbilisi, Батуми/Batumi, Кутаиси/Kutaisi) отображаются на выбранном языке интерфейса. Грузинские названия (თბილისი, ბათუმი) также поддерживаются.

---

## Быстрый старт за 5 минут

### Docker (рекомендуемый способ)

```bash
# 1. Клонируйте репозиторий
git clone https://github.com/mitetenov/tg-railway-monitor.git
cd tg-railway-monitor

# 2. Создайте .env из шаблона
cp .env.example .env
nano .env    # вставьте BOT_TOKEN от @BotFather

# 3. Запустите контейнер
docker compose up -d

# 4. Проверьте логи
docker compose logs -f
```

> **Примечание:** Проект использует Docker как основной способ деплоя. Образ автоматически собирается и публикуется как `mitetenov/tg-ticket-monitor`.

---

## Запуск через Docker

### Требования

- Docker Engine 24+ и Docker Compose v2+

### docker-compose.yml (уже в проекте)

```yaml
services:
  bot:
    image: mitetenov/tg-ticket-monitor:latest
    restart: unless-stopped
    env_file: .env
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

При запуске **без Docker Compose** (чистый `docker run`):

```bash
docker run -d --restart unless-stopped \
  --name tg-ticket-monitor \
  -e BOT_TOKEN=your_token_here \
  mitetenov/tg-ticket-monitor
```

В этом случае `docker-entrypoint.sh` сам сгенерирует `.env` внутри контейнера.

---

## Конфигурация (.env)

Файл `.env.example` содержит шаблон:

```ini
# Required:
BOT_TOKEN=your_bot_token_here
```

> **Важно:** файл `.env` НЕ должен попасть в Git — он добавлен в `.gitignore`.

---

## Структура проекта

> Полная информация о каждом модуле, тестах и инфраструктуре — в [structure.md](structure.md).

```
tg-railway-monitor/
├── bot.py                       # ⚡ Точка входа — Telegram-бот
├── ticket_monitor.py            # 🧠 Ядро: опрос API + diff состояний + нотификации
├── api.py                       # 📡 Фабрика API-клиентов + обратно-совместимые алиасы
├── api_tre.py                   # 📡 Реализация TreGeApi (поиск рейсов, билдер URL покупки)
├── _api_base.py                 # 📡 Абстрактный базовый класс TicketApi + константы
├── poller.py                    # 🔄 Фоновый asyncio-поллер (per-chat, pause/resume)
├── config_manager.py            # ⚙️ Управление конфигурацией чатов (JSON)
├── i18n.py                      # 🌐 Интернационализация (Translation, pluralisation, язык пользователя)
├── stations.py                  # 🚉 Единый источник данных о станциях (мастер-список, slug, RU/KA названия)
├── utils.py                     # 🛠 Утилиты (format_time, fmt_duration)
│
├── Dockerfile                   # 🐳 Образ Docker (python:3.11-alpine)
├── docker-compose.yml           # 🐳 Docker Compose с volume data/
├── docker-entrypoint.sh         # 🏁 Генерация .env из переменных окружения
├── DEPLOY.md                    # 📖 Документация по деплою
├── patch_slots.py               # 🔧 Патч python-telegram-bot для Python 3.13
│
├── README.md                    # 📖 Этот файл
├── api-docs.md                  # 📖 Документация API tre.ge
├── structure.md                 # 📖 Подробная архитектура проекта
├── .env.example                 # 📋 Шаблон .env
├── .gitignore                   # 🙈 Правила игнорирования Git
├── requirements.txt             # 📦 Python-зависимости
│
├── api_explorer.py              # 🔬 Интерактивный CLI-исследователь API
├── _debug_updater.py            # 🐛 Проверка класса Updater telegram-bot
├── _debug_slots.py              # 🐛 Анализ __slots__ и MRO Updater
│
├── sample_stations.json         # 📊 Примеры данных от API tre.ge
├── sample_rides.json
├── sample_calendar.json
├── sample_availability_today.json
├── sample_availability_tomorrow.json
│
├── data/                        # 📁 Per-чатовые JSON-конфиги (gitignored)
│   └── {chat_id}.json
│
└── tests/                       # 🧪 Тесты
    ├── test_api.py
    ├── test_api_base.py
    ├── test_api_factory.py
    ├── test_api_tre.py
    ├── test_bot.py
    ├── test_config_manager.py
    ├── test_config_manager_negative.py
    ├── test_i18n.py
    ├── test_poller.py
    ├── test_poller_grouped.py
    ├── test_poller_negative.py
    ├── test_poller_purchase_url.py
    ├── test_poller_time_format.py
    ├── test_ticket_monitor.py
    ├── test_ticket_monitor_negative.py
    ├── test_user_lang.py
    └── check_syntax.py
```

### Основные модули

| Модуль | Назначение |
|--------|-----------|
| `bot.py` | Точка входа. Регистрирует команды (`/start`, `/stop`, `/lang`), ConversationHandler мастера настройки (5 состояний), загружает станции при старте. |
| `ticket_monitor.py` | Ядро мониторинга. Класс `TicketMonitor` с фоновым threading-поллером. Без внешних зависимостей — только Python stdlib. |
| `api.py` | Фабрика API-клиентов. `get_ticket_api(source)` возвращает экземпляр `TicketApi`. Обратно-совместимые алиасы (`get_stations`, `get_available_rides`, `get_availability_calendar`) делегируют синглтону. |
| `api_tre.py` | Конкретная реализация `TreGeApi(TicketApi)`: поиск рейсов (`search_trips`), получение станций, билдер ссылки на покупку (`build_purchase_url`). |
| `_api_base.py` | Абстрактный класс `TicketApi` (ABC) с 5 абстрактными методами и константы `API_BASE`, `API_KEY`. |
| `poller.py` | Фоновый asyncio-поллер. Управляет per-chat задачами опроса API каждые 60 секунд. Состояние отслеживается через `_state` dict с посекундным диффом. Поддерживает `pause()`/`resume()`/`is_paused()`. |
| `config_manager.py` | CRUD для per-chat JSON-конфигов в `data/{chat_id}.json`. |
| `i18n.py` | Система интернационализации: класс `Translation` с интерполяцией и плюрализацией, автоопределение языка из профиля Telegram, `set_user_language()`, `translate_station_name()` с поддержкой EN/RU/KA названий. |
| `stations.py` | Единый источник данных о станциях: мастер-список `_STATION_DATA`, производные маппинги (code→data, slug→code), вспомогательные функции. |
| `utils.py` | Вспомогательные функции: `format_time()`, `fmt_duration()`. |

---

## API tre.ge

Бот использует публичное API [tre.ge](https://tre.ge) (Грузинская железная дорога).

**Базовый URL:** `https://gateway.tre.ge/integrations/api/GeorgianRailway`

**Эндпоинты:**

| Эндпоинт | Описание | Используется в |
|----------|----------|----------------|
| `GET /Dictionaries/civil-stations` | Список станций (латиница) | `bot.py`, `api_tre.py` |
| `GET /Availability/availability-calendar` | Календарь доступности на 30 дней | `api_explorer.py` |
| `GET /Availability/available-rides` | Рейсы с классами, ценами и местами | `poller.py`, `ticket_monitor.py` |
| `GET /Availability/availability-time-table` | Сводка популярных маршрутов | `api_explorer.py` |

> **API-ключ публичный:** `7d8d34d1-e9af-4897-9f0f-5c36c179be77` — вшит в клиентский JS tre.ge, не является секретом.

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
python3 -m pytest tests/test_bot.py -v

# С синтаксической проверкой
python3 tests/check_syntax.py
```

### CLI-исследователь API

```bash
python3 api_explorer.py
```

Интерактивный инструмент для изучения эндпоинтов tre.ge: станции, популярные маршруты, календарь доступности, рейсы по дате.

---

## Python 3.13 — известная проблема

Бот использует `python-telegram-bot==20.8`, у которого есть несовместимость с Python 3.13:

```
NameError: property __polling_cleanup_cb not found in __slots__
```

Причина: класс `Updater` в PTB 20.8 присваивает `self.__polling_cleanup_cb` в `__init__`, но не включает этот атрибут в `__slots__`.

**Решение:** проект включает `patch_slots.py`, который автоматически добавляет недостающий атрибут в `__slots__` класса `Updater`.

> **Docker** (рекомендуемый способ): образ использует `python:3.11-alpine`, где этой проблемы нет.

```bash
python3 patch_slots.py
```

---

## Лицензия

Проект распространяется без лицензионных ограничений. Используйте на свой страх и риск.
