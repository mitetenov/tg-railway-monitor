# tre.ge Telegram Ticket Monitor — Deployment

## 🐳 Docker (рекомендуемый способ)

### Требования

- Docker Engine 24+ и Docker Compose v2+
- Docker daemon включён в автозапуске:
  ```bash
  systemctl is-enabled docker   # должен быть enabled
  ```

### Быстрый запуск

```bash
cd /root/tg-ticket-monitor

# 1. Создайте .env с реальным BOT_TOKEN от @BotFather
cp .env.example .env
nano .env

# 2. Соберите и запустите
docker compose up -d

# 3. Проверьте статус
docker ps --filter name=tg-ticket-monitor

# 4. Логи
docker compose logs -f
```

Контейнер автоматически запускается при старте системы благодаря:
- **Docker daemon** включён в systemd (`systemctl enable docker`)
- **`restart: unless-stopped`** в `docker-compose.yml` — Docker перезапускает контейнер при каждом запуске демона

### Команды управления

| Действие | Команда |
|----------|---------|
| Запуск | `docker compose up -d` |
| Остановка | `docker compose down` |
| Перезапуск | `docker compose restart` |
| Логи (follow) | `docker compose logs -f` |
| Логи (последние 50) | `docker compose logs --tail=50` |
| Пересборка | `docker compose build --no-cache && docker compose up -d` |
| Проверка статуса | `docker ps --filter name=tg-ticket-monitor` |

### Переменные окружения

Передаются через `.env` файл (автоматически загружается `docker compose`):

| Переменная | Обязательно | Описание |
|-----------|-------------|----------|
| `BOT_TOKEN` | ✅ Да | Токен бота от [@BotFather](https://t.me/BotFather) |
| `ROUTE` | ❌ Нет | Код станции назначения (умолчание) |
| `DATE` | ❌ Нет | Дата поездки (умолчание, YYYY-MM-DD) |
| `CLASS` | ❌ Нет | Класс (1, 2, 3) |

### Персистентность данных

Per-chat конфиги хранятся в томе Docker `data:/app/data`. Данные сохраняются между перезапусками контейнера и не теряются при `docker compose down`.

```bash
# Просмотр данных внутри тома
docker run --rm -v tg-ticket-monitor_data:/data alpine ls -la /data
```

### Пересборка после изменений кода

```bash
cd /root/tg-ticket-monitor
git pull                         # или внесите изменения вручную
docker compose build --no-cache  # пересобрать образ
docker compose up -d             # перезапустить
```

---

## ⚠️ Миграция с systemd на Docker

Если ранее проект был установлен через systemd (bare-metal), выполните следующие шаги:

### 1. Остановите и отключите systemd-сервис

```bash
systemctl stop tg-ticket-monitor
systemctl disable tg-ticket-monitor
rm /etc/systemd/system/tg-ticket-monitor.service
rm /etc/systemd/system/multi-user.target.wants/tg-ticket-monitor.service
systemctl daemon-reload
```

### 2. Убедитесь, что данные не потеряются

Per-chat конфиги находятся в `/root/tg-ticket-monitor/data/`. Docker-композ использует том `data:/app/data`. При первом запуске `docker compose up`:
- Если том ещё не существует — Docker создаёт пустой том
- Данные из `/root/tg-ticket-monitor/data/` **не копируются в том автоматически**

**Чтобы сохранить существующие данные:**
```bash
# Скопировать данные в том Docker
docker run --rm \
  -v /root/tg-ticket-monitor/data:/src \
  -v tg-ticket-monitor_data:/dst \
  alpine sh -c "cp -r /src/* /dst/ 2>/dev/null; ls -la /dst"
```

Или используйте bind mount вместо тома (временно измените `docker-compose.yml`):
```yaml
volumes:
  - /root/tg-ticket-monitor/data:/app/data  # bind mount вместо named volume
```

### 3. Перенесите .env

Файл `.env` уже находится в `/root/tg-ticket-monitor/.env` и будет автоматически загружен `docker compose`.

### 4. Запустите Docker-контейнер

```bash
docker compose up -d
```

### 5. Проверьте логи

```bash
docker compose logs -f
```

---

## 🗑️ Устаревший способ: systemd (legacy)

> **Проект переведён на Docker в июне 2026.**
> Инструкции по systemd-деплою сохранены в репозитории для истории:
> - `deploy.sh` — скрипт деплоя (legacy)
> - `tg-ticket-monitor.service` — unit-файл (legacy)
> - README.md → раздел «Запуск через systemd (устаревший способ)»

Вкратце, для bare-metal запуска требовалось:
1. Установить зависимости в `.venv`
2. Применить `patch_slots.py` (для Python 3.13)
3. Установить systemd unit и запустить сервис

Docker решает все эти проблемы «из коробки» — изолированное окружение, фиксированная версия Python, автозапуск через restart policy.
