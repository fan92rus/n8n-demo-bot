"""Конфиг демо-бота из окружения."""

import os

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
N8N_BASE_URL = os.environ.get("N8N_BASE_URL", "http://192.168.1.111:5678")
N8N_TIMEOUT = float(os.environ.get("N8N_TIMEOUT", "90"))
