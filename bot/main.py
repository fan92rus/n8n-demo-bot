"""Демо-бот студии: Telegram-шелл, вся логика в n8n-воркфлоу на CT100.

Архитектура: aiogram long polling (только исходящие соединения, никаких
публичных вебхуков/TLS) -> n8n webhooks по LAN. Интерактив:
  /start — меню
  /classify <текст> или просто текст — ИИ-классификатор заявки
  /wizard — подбор услуги: кнопки меняются по шагам (n8n возвращает новую раскладку)
  /slots — свободные слоты (inline-кнопки)
  текст без команды — заявка: ИИ определит, заявка ли это, и сохранит
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

from bot.config import BOT_TOKEN, N8N_BASE_URL, N8N_TIMEOUT
from bot.format import format_booking, format_classify, format_leads, format_slots
from bot.n8n_client import N8nClient, N8nError

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
log = logging.getLogger("demo-bot")

dp = Dispatcher()
n8n = N8nClient(N8N_BASE_URL, timeout=N8N_TIMEOUT)

WELCOME = (
    "Привет! Я демо-бот IT-студии: заявки и запись клиентов работают через n8n.\n\n"
    "• Напишите текстом, что нужно сделать, — это станет вашей заявкой\n"
    "   (ИИ определит категорию и сохранит её, видно будет только вам)\n"
    "• Если это не заявка — подскажу, что написать\n"
    "• /slots — свободные слоты, запись в один клик\n"
    "• /wizard — подбор услуги за 3 клика\n"
    "• /my — ваши записи и отмена\n"
    "• /leads — ваши заявки\n"
    "• Кнопка ниже — мини-апп: каталог, слоты, заявки"
)

# Постоянное меню-клавиатура (кнопки под полем ввода)
BTN_CLASSIFY = "🧾 Классификация"
BTN_SLOTS = "📅 Слоты"
BTN_WIZARD = "🪄 Подбор услуги"
BTN_MY = "🗂 Мои записи"
BTN_LEADS = "📋 Лиды"
BTN_HELP = "ℹ️ Помощь"

MENU_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=BTN_CLASSIFY), KeyboardButton(text=BTN_SLOTS)],
        [KeyboardButton(text=BTN_WIZARD), KeyboardButton(text=BTN_MY)],
        [KeyboardButton(text=BTN_LEADS), KeyboardButton(text=BTN_HELP)],
    ],
    resize_keyboard=True,
    input_field_placeholder="Текст заявки можно писать прямо сюда",
)

BOT_COMMANDS = [
    BotCommand(command="start", description="Меню"),
    BotCommand(command="classify", description="Классификация заявки"),
    BotCommand(command="slots", description="Свободные слоты"),
    BotCommand(command="wizard", description="Подбор услуги (кнопки по шагам)"),
    BotCommand(command="my", description="Мои записи и отмена"),
    BotCommand(command="leads", description="Ваши заявки (приватно)"),
    BotCommand(command="help", description="Помощь"),
]


async def safe_answer(m: Message, text: str, kb: InlineKeyboardMarkup | None = None) -> None:
    """Ответ с подавлением сетевых сбоев, чтобы воркер не падал."""
    try:
        await m.answer(text, reply_markup=kb)
    except Exception:  # noqa: BLE001
        log.exception("answer failed")


def kb_from_buttons(rows: list | None) -> InlineKeyboardMarkup | None:
    """Раскладка wizard'а из ответа n8n: [[{"text","callback_data"}]]."""
    if not rows:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=b["text"], callback_data=b["callback_data"]) for b in row]
            for row in rows
        ]
    )


async def run_wizard(m: Message, sel: str = "start") -> None:
    try:
        step = await n8n.wizard(sel)
    except N8nError:
        await safe_answer(m, "Сервис недоступен, попробуйте позже.")
        return
    await safe_answer(m, step.get("text", "…"), kb_from_buttons(step.get("buttons")))


@dp.message(Command("wizard"))
async def cmd_wizard(m: Message) -> None:
    await run_wizard(m)


@dp.message(F.text == BTN_WIZARD)
async def btn_wizard(m: Message) -> None:
    await run_wizard(m)


@dp.callback_query(F.data.startswith("wz:"))
async def cb_wizard(q: CallbackQuery) -> None:
    sel = (q.data or "")[3:64]
    try:
        step = await n8n.wizard(sel)
        text = step.get("text", "…")
        kb = kb_from_buttons(step.get("buttons"))
    except N8nError:
        text, kb = "Сервис недоступен, попробуйте позже.", None
    try:
        await q.message.edit_text(text, reply_markup=kb)  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        pass  # текст/клавиатура не изменились — Telegram вернёт ошибку, это нормально
    await q.answer()


@dp.message(Command("start"))
async def cmd_start(m: Message) -> None:
    await safe_answer(m, WELCOME)
    await m.answer("Меню всегда под клавиатурой 👇", reply_markup=MENU_KB)
    kb = miniapp_kb()
    if kb:
        await safe_answer(m, "Каталог, слоты и запись — прямо в Telegram:", kb)


@dp.message(Command("help"))
async def cmd_help(m: Message) -> None:
    await safe_answer(m, WELCOME)


async def run_classify(m: Message, text: str) -> None:
    user = display_name(m.from_user)
    wait = await m.answer("Думаю…")
    try:
        result = await n8n.classify(text[:2000], user)
    except N8nError as e:
        log.warning("classify failed: %s", e)
        await wait.edit_text("Сервис классификации недоступен, попробуйте позже.")
        return
    if result.get("is_request") is False:
        await wait.edit_text(
            "Похоже, это не заявка 🙂 Напишите, что нужно сделать, — например: "
            "«нужен бот, который принимает заявки с сайта в Google-таблицу» — и я оформлю заявку."
        )
        return
    saved = "" if result.get("lead_saved") is False else "\n\n✅ Заявка сохранена — она в /leads и в мини-аппе."
    await wait.edit_text(format_classify(result) + saved)


@dp.message(Command("classify"))
async def cmd_classify(m: Message, command: CommandObject) -> None:
    text = (command.args or "").strip()
    if not text:
        await safe_answer(m, "Пришли текст заявки: /classify настроить CRM")
        return
    await run_classify(m, text)


@dp.message(Command("slots"))
async def cmd_slots(m: Message) -> None:
    await show_slots(m)


@dp.message(F.text == BTN_SLOTS)
async def btn_slots(m: Message) -> None:
    await show_slots(m)


@dp.message(F.text == BTN_HELP)
async def btn_help(m: Message) -> None:
    await safe_answer(m, WELCOME)


def miniapp_kb() -> InlineKeyboardMarkup | None:
    """Кнопка мини-аппа; Telegram принимает только https-URL."""
    if not WEBAPP_URL.startswith("https://"):
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🖥 Открыть мини-апп", web_app=WebAppInfo(url=WEBAPP_URL))]]
    )


@dp.message(F.text == BTN_CLASSIFY)
async def btn_classify(m: Message) -> None:
    await safe_answer(m, "Просто пришли текст заявки следующим сообщением — ИИ определит категорию.")


async def show_slots(m: Message) -> None:
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


WEBAPP_URL = os.environ.get("WEBAPP_URL", "")


def display_name(u) -> str:
    """Кого показывать в записях и лидах: @username или id."""
    return f"@{u.username}" if u and u.username else str(getattr(u, "id", "?"))


@dp.message(Command("my"))
@dp.message(F.text == BTN_MY)
async def handler_my(m: Message) -> None:
    user = display_name(m.from_user)
    try:
        data = await n8n.my_bookings(user)
    except N8nError:
        await safe_answer(m, "Расписание недоступно, попробуйте позже.")
        return
    bookings = data.get("bookings", []) if isinstance(data, dict) else []
    if not bookings:
        await safe_answer(m, "Записей нет. /slots — выбрать слот, /wizard — подобрать услугу.")
        return
    rows = [
        [InlineKeyboardButton(text=f"❌ {b.get('start', b.get('slot_id', '?'))}", callback_data=f"mycancel:{b.get('slot_id')}")]
        for b in bookings
    ]
    await m.answer(
        "Твои записи — нажми, чтобы отменить (слот освободится):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@dp.callback_query(F.data.startswith("mycancel:"))
async def cb_mycancel(q: CallbackQuery) -> None:
    slot_id = (q.data or "").split(":", 1)[1]
    user = display_name(q.from_user)
    try:
        result = await n8n.cancel_booking(slot_id, user)
        text = (
            f"✅ Отменено: {result.get('freed', slot_id)}. Слот снова свободен."
            if result.get("ok")
            else f"⚠️ {result.get('error', 'не удалось отменить')}"
        )
    except N8nError:
        text = "Сервис недоступен, попробуйте позже."
    try:
        await q.message.edit_text(text)  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        pass
    await q.answer()


@dp.message(Command("leads"))
@dp.message(F.text == BTN_LEADS)
async def handler_leads(m: Message) -> None:
    try:
        data = await n8n.leads(user=display_name(m))
    except N8nError:
        await safe_answer(m, "Сервис недоступен, попробуйте позже.")
        return
    leads = data.get("leads", []) if isinstance(data, dict) else []
    private = bool(data.get("leads_private", True)) if isinstance(data, dict) else True
    await safe_answer(m, format_leads(leads, private=private))


@dp.message(F.text)
async def free_text(m: Message) -> None:
    """Любой свободный текст = заявка на классификацию (интерактивная демка)."""
    await run_classify(m, m.text or "")


async def main() -> None:
    if not BOT_TOKEN:
        log.error("BOT_TOKEN не задан")
        return
    bot = Bot(BOT_TOKEN)
    await bot.set_my_commands(BOT_COMMANDS)
    log.info("demo-bot up, n8n=%s", N8N_BASE_URL)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
