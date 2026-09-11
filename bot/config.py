"""Конфиг демо-бота из окружения."""

import logging
import os

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
DEMO_SIGN_SECRET = os.environ.get("DEMO_SIGN_SECRET", "")
N8N_BASE_URL = os.environ.get("N8N_BASE_URL", "http://192.168.1.111:5678")
try:
    N8N_TIMEOUT = float(os.environ.get("N8N_TIMEOUT", "90"))
except ValueError:
    logging.getLogger("demo-bot").warning("N8N_TIMEOUT не число, использую 90")
    N8N_TIMEOUT = 90.0
