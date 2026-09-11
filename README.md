# n8n-demo-bot

Демо-бот S-04 (витрина n8n-интеграций): Telegram-шелл, вся логика — в n8n-воркфлоу
на демо-стенде (CT100, http://192.168.1.111:5678).

Архитектура: aiogram long polling (только исходящие соединения — не нужны публичный
IP, порты и TLS-сертификаты) → n8n webhooks по LAN.

## Команды

| Команда | Что делает | Воркфлоу n8n |
|---|---|---|
| `/start`, `/help` | меню | — |
| `/classify <текст>` или просто текст | ИИ-классификатор заявки (категория/приоритет/суть) | demo-09 `/webhook/demo/classify` |
| `/slots` | свободные слоты (inline-кнопки) | `/webhook/demo/slots` (в работе) |
| `/book <id>` или кнопка | запись на слот | `/webhook/demo/book` (в работе) |

## Запуск

```bash
pip install -r requirements.txt
BOT_TOKEN=... N8N_BASE_URL=http://192.168.1.111:5678 python -m bot.main
```

## Деплой (CT100)

```bash
docker build -t n8n-demo-bot:latest .
docker run -d --name n8n-demo-bot --restart unless-stopped \
  --env-file /root/n8n-demo-bot.env \
  -e N8N_BASE_URL=http://192.168.1.111:5678 n8n-demo-bot:latest
```

`/root/n8n-demo-bot.env`: `BOT_TOKEN=...` (секрет, вне git).

## CI

Gitea Actions: ruff + pytest на каждый push в main/dev (`.gitea/workflows/build.yml`).

## Тесты

Клиент n8n и форматтеры покрыты unit-тестами на httpx.MockTransport — сеть и
aiogram не нужны: `pytest -q`.

## Мини-апп (Telegram WebApp)

Страница: https://funnyhome.netcraze.pro/ — CT100: nginx (8091) → Traefik (Let's Encrypt, домен оператора).
Бэкенд из страницы — те же n8n-вебхуки `/webhook/demo/*`: каталог услуг → слоты → запись → отмена.
Кнопка «🖥 Открыть мини-апп» появляется в /start при заданном `WEBAPP_URL` (только https).
