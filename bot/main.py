"""Демо-бот студии: Telegram-шелл, вся логика в n8n-воркфлоу на CT100.

Архитектура: aiogram long polling (только исходящие соединения, никаких
публичных вебхуков/TLS) -> n8n webhooks по LAN. Интерактив:
  /start — меню
  /classify <текст> или просто текст — ИИ-классификатор заявки
  /slots — свободные слоты (inline-кнопки)
  /book <id> — запись на слот
"""

from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.config import BOT_TOKEN, N8N_BASE_URL, N8N_TIMEOUT
from bot.format import format_booking, format_classify, format_slots
from bot.n8n_client import N8nClient, N8nError

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
log = logging.getLogger("demo-bot")

dp = Dispatcher()
n8n = N8nClient(N8N_BASE_URL, timeout=N8N_TIMEOUT)

WELCOME = (
    "Привет! Я демо-бот IT-студии: покажу, как заявки и запись клиентов "
    "работают через n8n.\n\n"
    "• Кинь текст заявки (или /classify <текст>) — ИИ определит категорию\n"
    "• /slots — свободные слоты для записи\n"
    "• /book <id> — записаться"
)


async def safe_answer(m: Message, text: str) -> None:
    """Ответ с подавлением сетевых сбоев, чтобы воркер не падал."""
    try:
        await m.answer(text)
    except Exception:  # noqa: BLE001
        log.exception("answer failed")


@dp.message(Command("start"))
async def cmd_start(m: Message) -> None:
    await safe_answer(m, WELCOME)


@dp.message(Command("help"))
async def cmd_help(m: Message) -> None:
    await safe_answer(m, WELCOME)


async def run_classify(m: Message, text: str) -> None:
    wait = await m.answer("Думаю…")
    try:
        result = await n8n.classify(text[:2000])
        await wait.edit_text(format_classify(result))
    except N8nError as e:
        log.warning("classify failed: %s", e)
        await wait.edit_text("Сервис классификации недоступен, попробуйте позже.")


@dp.message(Command("classify"))
async def cmd_classify(m: Message, command: CommandObject) -> None:
    text = (command.args or "").strip()
    if not text:
        await safe_answer(m, "Пришли текст заявки: /classify настроить CRM")
        return
    await run_classify(m, text)


@dp.message(Command("slots"))
async def cmd_slots(m: Message) -> None:
    try:
        slots = await n8n.slots()
    except N8nError:
        await safe_answer(m, "Расписание недоступно, попробуйте позже.")
        return
    if not slots:
        await safe_answer(m, format_slots(slots))
        return
    rows = [
        [
            InlineKeyboardButton(
                text=f"{s.get('label', s.get('id'))} {s.get('start', '')}".strip(),
                callback_data=f"book:{s.get('id')}",
            )
        ]
        for s in slots
    ]
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    await m.answer("Свободные слоты — нажми, чтобы записаться:", reply_markup=kb)


async def run_book(m: Message, slot_id: str) -> None:
    user = f"@{m.from_user.username}" if m.from_user and m.from_user.username else str(m.from_user.id)
    try:
        result = await n8n.book(slot_id, user)
        await safe_answer(m, format_booking(result))
    except N8nError:
        await safe_answer(m, "Запись недоступна, попробуйте позже.")


@dp.message(Command("book"))
async def cmd_book(m: Message, command: CommandObject) -> None:
    slot_id = (command.args or "").strip()
    if not slot_id:
        await safe_answer(m, "Укажи слот: /book <id> (список — /slots)")
        return
    await run_book(m, slot_id)


@dp.callback_query(F.data.startswith("book:"))
async def cb_book(q: CallbackQuery) -> None:
    slot_id = (q.data or "").split(":", 1)[1]
    user = (
        f"@{q.from_user.username}" if q.from_user and q.from_user.username else str(q.from_user.id)
    )
    try:
        result = await n8n.book(slot_id, user)
        text = format_booking(result)
    except N8nError:
        text = "Запись недоступна, попробуйте позже."
    await q.message.edit_text(text)  # type: ignore[union-attr]
    await q.answer()


@dp.message(F.text)
async def free_text(m: Message) -> None:
    """Любой свободный текст = заявка на классификацию (интерактивная демка)."""
    await run_classify(m, m.text or "")


async def main() -> None:
    if not BOT_TOKEN:
        log.error("BOT_TOKEN не задан")
        return
    bot = Bot(BOT_TOKEN)
    log.info("demo-bot up, n8n=%s", N8N_BASE_URL)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
