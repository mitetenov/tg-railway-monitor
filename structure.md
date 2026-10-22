# Структура проекта

```text
main.go                  запуск, окружение, HTTP-клиенты, SIGTERM
bot.go                   мастер /start, /stop, /lang, Telegram long polling
telegram.go              типы обновлений и клиент Telegram Bot API
railway.go               клиент tre.ge, классы мест, ссылка покупки
poller.go                проверка каждые 60 с, сравнение и уведомления
storage.go               атомарная запись конфигов и снимков
i18n.go                 встроенные переводы и названия станций
stations.json            единый справочник станций
locales/{en,ru}/          сообщения интерфейса
*_test.go                поведенческие тесты, HTTP/TLS, конкурентность
testdata/                эталоны уведомлений из Python
sample_*.json            образцы ответов tre.ge
data/                    конфиги и снимки чатов (gitignored)
Dockerfile               Go build → scratch runtime
docker-compose.yml       запуск и постоянный том
```

Поток данных: обновление Telegram → мастер → JSON-конфиг → фоновая проверка tre.ge
→ сравнение с JSON-снимком → уведомление Telegram → сохранение нового снимка.
Рабочие горутины разделяют HTTP-клиенты; остановка чата отменяет запросы и ждёт
завершения его проверки перед удалением настроек.
