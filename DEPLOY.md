# Развёртывание и переход на Go

```sh
cp .env.example .env  # BOT_TOKEN от @BotFather
docker compose up -d --build
docker compose logs -f
```

Для опубликованного образа: `docker compose pull && docker compose up -d`.
Рекомендуется фиксировать тег/дайджест образа при обновлениях. CI публикует образ
только после push в main; локальная сборка сама ничего не публикует.

## Обновление существующего Python-бота

Go читает прежние `data/{chat_id}.json` и `data/{chat_id}.state.json` без конвертации.
Сохраняйте существующий Compose project name и том `data:/app/data`. Не запускайте
две копии бота с одним токеном одновременно: Telegram long polling конфликтует.

1. Сохраните текущий тег/дайджест образа для отката и сделайте резервную копию тома.
2. Соберите новый образ: `docker compose build`.
3. Обновите контейнер: `docker compose up -d`.
4. Проверьте логи: сообщение `Ticket monitor started`, число `restored_chats` и
   отсутствие ошибок записи или API. Настройки в Telegram задаются через `/start`.

Пример резервной копии (подставьте фактическое имя тома):

```sh
docker compose stop bot
docker run --rm -v tg-railway-monitor_data:/data:ro -v "$PWD":/backup \
  alpine tar czf /backup/railway-data-backup.tgz -C /data .
docker compose up -d
```

Для отката верните прежний тег/дайджест в `image`, затем выполните
`docker compose up -d --no-build`. Форматы конфигов и снимков обратно совместимы.
Незавершённый мастер настройки в память не сохраняется: начните его заново
командой `/start` после перезапуска.

## Права данных

Контейнер сохраняет UID/GID **1000:1000**. Существующие тома продолжают работать.
При недоступном каталоге бот завершится с понятной ошибкой до подключения Telegram.
Если том создан старым образом с другим владельцем, исправьте владельца явно:

```sh
docker compose stop bot
docker run --rm -v tg-railway-monitor_data:/data alpine chown -R 1000:1000 /data
docker compose up -d
```

Для проверки образа без сети/токена и без доступа к рабочему тому:

```sh
docker run --rm --network none --read-only \
  --tmpfs /app/data:uid=1000,gid=1000,mode=700 \
  tg-ticket-monitor:local --check
```

В `scratch` нет shell: просмотр данных и резервные копии выполняйте отдельным
временным контейнером с подключённым томом. SIGTERM корректно отменяет запросы и
дожидается завершения фоновых проверок; стандартного времени остановки Compose хватает.
