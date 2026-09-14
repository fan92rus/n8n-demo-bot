"""Юнит-тесты обработчиков bot/main.py на поддельных апдейтах и поддельном n8n.

Без реального Telegram и без реального n8n: цель — закрыть дыру в покрытии
(из 31 функции 25 были без покрытия), из-за которой проскочил блокер B1.
Проверяются все ветки кнопок: book:, lc:, mycancel:, wz:.
"""

from __future__ import annotations

import pytest

from bot import main
from bot.n8n_client import N8nError

SLOT = {"id": "2026-09-16-1000", "label": "утро", "start": "2026-09-16 10:00 (утро)"}
SLOT2 = {"id": "2026-09-17-1400", "label": "день", "start": "2026-09-17 14:00 (день)"}


# ─────────────────────────── поддельные Telegram-объекты ───────────────────────────
class FakeUser:
    def __init__(self, id=101, username="alice"):
        self.id = id
        self.username = username


class FakeChat:
    def __init__(self, id=500, type="private"):
        self.id = id
        self.type = type


class FakeSent:
    """Результат m.answer() — умеет edit_text (как настоящее сообщение)."""

    def __init__(self, text=None, fail_edit=False):
        self.text = text
        self.fail_edit = fail_edit
        self.edits: list = []
        self.answers: list = []

    async def edit_text(self, text, reply_markup=None, **kw):
        if self.fail_edit:
            raise RuntimeError("network down")
        self.edits.append((text, reply_markup))
        self.text = text

    async def answer(self, text, reply_markup=None, **kw):
        self.answers.append((text, reply_markup))
        return self


class FakeMessage:
    def __init__(self, text=None, chat=None, user=None, fail_edit=False):
        self.text = text
        self.chat = chat or FakeChat()
        self.from_user = user or FakeUser()
        self.fail_edit = fail_edit
        self.replies: list = []
        self.sent: list[FakeSent] = []

    async def answer(self, text, reply_markup=None, **kw):
        self.replies.append((text, reply_markup))
        s = FakeSent(text, fail_edit=self.fail_edit)
        self.sent.append(s)
        return s


class FakeCallback:
    def __init__(self, data, user=None, message=None):
        self.data = data
        self.from_user = user or FakeUser()
        self.message = message or FakeSent()
        self.answered = 0

    async def answer(self, *a, **kw):
        self.answered += 1


class FakeN8n:
    """Поддельный клиент n8n: записывает вызовы, возвращает настроенные ответы."""

    def __init__(self):
        self.calls: list = []
        self.slots_result = [dict(SLOT), dict(SLOT2)]
        self.classify_result = {
            "ok": True,
            "is_request": True,
            "needs_clarification": False,
            "lead_saved": True,
            "lead_id": "L7",
            "category": "бот",
            "priority": "средний",
            "summary": "телеграм-бот",
        }
        self.book_result = {"ok": True, "booking": {"slot_id": SLOT["id"], "start": SLOT["start"]}}
        self.wizard_result = {
            "text": "шаг",
            "buttons": [[{"text": "старт", "callback_data": "wz:start"}]],
        }
        self.my_result = {"ok": True, "bookings": []}
        self.cancel_result = {"ok": True, "freed": "2026-09-16 10:00"}
        self.lead_date_result = {"ok": True}
        self.errors: dict[str, Exception] = {}

    def _rec(self, name, *args, **kw):
        self.calls.append((name, args, kw))
        if name in self.errors:
            raise self.errors[name]

    async def slots(self):
        self._rec("slots")
        return self.slots_result

    async def classify(self, text, user=None):
        self._rec("classify", text, user)
        return self.classify_result

    async def book(self, slot_id, user):
        self._rec("book", slot_id, user)
        return self.book_result

    async def wizard(self, sel, user=None):
        self._rec("wizard", sel, user)
        return self.wizard_result

    async def my_bookings(self, user):
        self._rec("my", user)
        return self.my_result

    async def cancel_booking(self, slot_id, user):
        self._rec("cancel", slot_id, user)
        return self.cancel_result

    async def lead_date(self, user, date, lead_id=None):
        self._rec("lead_date", user, date, lead_id)
        return self.lead_date_result

    def calls_of(self, name):
        return [c for c in self.calls if c[0] == name]


@pytest.fixture()
def fake_n8n(monkeypatch):
    fake = FakeN8n()
    monkeypatch.setattr(main, "n8n", fake)
    main.PENDING_CLARIFY.clear()
    main.CHAT_LOCKS.clear()
    return fake


def _edits(msg_or_sent):
    if isinstance(msg_or_sent, FakeMessage):
        return [t for s in msg_or_sent.sent for (t, _kb) in s.edits]
    return [t for (t, _kb) in msg_or_sent.edits]


# ─────────────────────────────────── /start, /help ───────────────────────────────────
async def test_cmd_start_welcome_menu_and_miniapp(fake_n8n, monkeypatch):
    monkeypatch.setattr(main, "WEBAPP_URL", "https://funnyhome.netcraze.pro/")
    m = FakeMessage()
    await main.cmd_start(m)
    assert "Привет!" in m.replies[0][0]
    assert m.replies[1][1] is main.MENU_KB  # меню-клавиатура
    assert m.replies[2][1] is not None  # кнопка мини-аппа (https)


async def test_cmd_start_without_webapp_url(fake_n8n, monkeypatch):
    monkeypatch.setattr(main, "WEBAPP_URL", "")
    m = FakeMessage()
    await main.cmd_start(m)
    assert len(m.replies) == 2  # только приветствие+меню, без кнопки мини-аппа


async def test_cmd_start_resets_pending(fake_n8n):
    main.pending_put(500, 101, "старое уточнение")
    await main.cmd_start(FakeMessage(chat=FakeChat(id=500), user=FakeUser(id=101)))
    assert main.pending_get(500, 101) is None


async def test_cmd_help_and_btn_help(fake_n8n):
    for handler in (main.cmd_help, main.btn_help):
        m = FakeMessage()
        await handler(m)
        assert "Привет!" in m.replies[0][0]


async def test_miniapp_kb_only_https(monkeypatch):
    monkeypatch.setattr(main, "WEBAPP_URL", "http://insecure.local/")
    assert main.miniapp_kb() is None
    monkeypatch.setattr(main, "WEBAPP_URL", "https://ok.local/")
    kb = main.miniapp_kb()
    assert kb is not None and kb.inline_keyboard[0][0].web_app.url == "https://ok.local/"


# ─────────────────────────────────── /slots ───────────────────────────────────
async def test_cmd_slots_and_btn_slots_show_buttons(fake_n8n):
    for handler in (main.cmd_slots, main.btn_slots):
        m = FakeMessage()
        await handler(m)
        text, kb = m.replies[0]
        assert SLOT["start"] in text and SLOT2["id"] in str(kb)
        callbacks = [b.callback_data for row in kb.inline_keyboard for b in row]
        assert f"book:{SLOT['id']}" in callbacks


async def test_show_slots_empty(fake_n8n):
    fake_n8n.slots_result = []
    m = FakeMessage()
    await main.show_slots(m)
    assert "нет" in m.replies[0][0].lower()
    assert m.replies[0][1] is None


async def test_show_slots_service_unavailable(fake_n8n):
    fake_n8n.errors["slots"] = N8nError("boom")
    m = FakeMessage()
    await main.show_slots(m)
    assert "недоступно" in m.replies[0][0]


# ─────────────────────────────────── /wizard ───────────────────────────────────
async def test_cmd_wizard_and_btn_wizard(fake_n8n):
    for handler in (main.cmd_wizard, main.btn_wizard):
        m = FakeMessage()
        await handler(m)
        assert m.replies[0][0] == "шаг"
        assert m.replies[0][1] is not None
    assert fake_n8n.calls_of("wizard")[0][1] == ("start", "@alice")


async def test_run_wizard_service_unavailable(fake_n8n):
    fake_n8n.errors["wizard"] = N8nError("down")
    m = FakeMessage()
    await main.run_wizard(m)
    assert "недоступен" in m.replies[0][0]


async def test_cb_wizard_edits_and_answers(fake_n8n):
    q = FakeCallback("wz:srv:dev")
    await main.cb_wizard(q)
    assert q.answered == 1
    assert q.message.edits[0][0] == "шаг"
    assert fake_n8n.calls_of("wizard")[0][1] == ("srv:dev", "@alice")


async def test_cb_wizard_service_unavailable(fake_n8n):
    fake_n8n.errors["wizard"] = N8nError("down")
    q = FakeCallback("wz:start")
    await main.cb_wizard(q)
    assert "недоступен" in q.message.edits[0][0]
    assert q.answered == 1


# ─────────────────────────────────── book: callback ───────────────────────────────────
async def test_cb_book_success(fake_n8n):
    q = FakeCallback(f"book:{SLOT['id']}")
    await main.cb_book(q)
    assert "Записал" in q.message.edits[0][0]
    assert q.answered == 1
    assert fake_n8n.calls_of("book")[0][1] == (SLOT["id"], "@alice")


async def test_cb_book_idempotent_double_tap_keeps_success(fake_n8n):
    """S3: двойной тап по слоту не переписывает успех на провал."""
    fake_n8n.book_result = {
        "ok": True,
        "idempotent": True,
        "booking": {"slot_id": SLOT["id"], "start": SLOT["start"]},
    }
    q1, q2 = FakeCallback(f"book:{SLOT['id']}"), FakeCallback(f"book:{SLOT['id']}")
    await main.cb_book(q1)
    await main.cb_book(q2)
    assert "Записал" in q1.message.edits[0][0]
    assert "Записал" in q2.message.edits[0][0]
    assert "Не получилось" not in q2.message.edits[0][0]


async def test_cb_book_occupied_by_other(fake_n8n):
    fake_n8n.book_result = {"ok": False, "error": "слот занят другим пользователем"}
    q = FakeCallback(f"book:{SLOT['id']}")
    await main.cb_book(q)
    assert "занят другим" in q.message.edits[0][0]


async def test_cb_book_service_unavailable(fake_n8n):
    fake_n8n.errors["book"] = N8nError("down")
    q = FakeCallback(f"book:{SLOT['id']}")
    await main.cb_book(q)
    assert "недоступна" in q.message.edits[0][0]


# ─────────────────────────────────── /my + mycancel ───────────────────────────────────
async def test_handler_my_lists_bookings(fake_n8n):
    fake_n8n.my_result = {
        "ok": True,
        "bookings": [
            {"slot_id": SLOT["id"], "start": SLOT["start"]},
            {"slot_id": SLOT2["id"], "start": SLOT2["start"]},
        ],
    }
    m = FakeMessage()
    await main.handler_my(m)
    kb = m.replies[0][1]
    callbacks = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert f"mycancel:{SLOT['id']}" in callbacks and f"mycancel:{SLOT2['id']}" in callbacks


async def test_handler_my_empty(fake_n8n):
    m = FakeMessage()
    await main.handler_my(m)
    assert "Записей нет" in m.replies[0][0]


async def test_handler_my_garbage_rows_filtered(fake_n8n):
    fake_n8n.my_result = {"ok": True, "bookings": ["мусор", {}, {"slot_id": "", "start": "x"}]}
    m = FakeMessage()
    await main.handler_my(m)
    assert "Записей нет" in m.replies[0][0]


async def test_handler_my_service_unavailable(fake_n8n):
    fake_n8n.errors["my"] = N8nError("down")
    m = FakeMessage()
    await main.handler_my(m)
    assert "недоступно" in m.replies[0][0]


async def test_cb_mycancel_success(fake_n8n):
    q = FakeCallback(f"mycancel:{SLOT['id']}")
    await main.cb_mycancel(q)
    assert "Отменено" in q.message.edits[0][0]
    assert q.answered == 1


async def test_cb_mycancel_refused(fake_n8n):
    fake_n8n.cancel_result = {"ok": False, "error": "это не ваша бронь"}
    q = FakeCallback(f"mycancel:{SLOT['id']}")
    await main.cb_mycancel(q)
    assert "не ваша бронь" in q.message.edits[0][0]


async def test_cb_mycancel_service_unavailable(fake_n8n):
    fake_n8n.errors["cancel"] = N8nError("down")
    q = FakeCallback(f"mycancel:{SLOT['id']}")
    await main.cb_mycancel(q)
    assert "недоступен" in q.message.edits[0][0]


# ─────────────────────────────────── /classify + free text ───────────────────────────────────
async def test_cmd_classify_without_args(fake_n8n):
    m = FakeMessage(text="/classify")
    await main.cmd_classify(m, _CmdArgs(None))
    assert "Пришли текст" in m.replies[0][0]


async def test_cmd_classify_with_args(fake_n8n):
    m = FakeMessage(text="/classify настроить CRM")
    await main.cmd_classify(m, _CmdArgs("настроить CRM"))
    assert fake_n8n.calls_of("classify")[0][1][0] == "настроить CRM"


async def test_run_classify_saved_and_offers_consult(fake_n8n):
    m = FakeMessage(text="нужен бот")
    await main.run_classify(m, "нужен бот")
    assert "Заявка сохранена" in m.sent[0].edits[0][0]
    assert "консультации" in m.replies[-1][0]  # offer_consult
    assert fake_n8n.calls_of("lead_date") == []


async def test_run_classify_passes_lead_id_into_consult_buttons(fake_n8n):
    m = FakeMessage(text="нужен бот")
    await main.run_classify(m, "нужен бот")
    kb = m.replies[-1][1]
    callbacks = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert f"lc:{SLOT['id']}:L7" in callbacks  # M5: lead_id в callback


async def test_run_classify_not_a_request(fake_n8n):
    fake_n8n.classify_result = {"ok": True, "is_request": False, "lead_saved": False}
    m = FakeMessage(text="привет")
    await main.run_classify(m, "привет")
    assert "не заявка" in m.sent[0].edits[0][0]


async def test_run_classify_needs_clarification_then_merge(fake_n8n):
    fake_n8n.classify_result = {
        "ok": True,
        "is_request": True,
        "needs_clarification": True,
        "clarify_question": "что именно автоматизировать?",
        "lead_saved": False,
    }
    m = FakeMessage(text="нужен бот")
    await main.run_classify(m, "нужен бот")
    assert "уточню" in m.sent[0].edits[0][0]
    assert main.pending_get(500, 101) == "нужен бот"
    # второе сообщение — уточнение, текст склеивается с первым
    fake_n8n.classify_result = {
        "ok": True, "is_request": True, "needs_clarification": False, "lead_saved": True,
        "category": "бот", "priority": "средний", "summary": "приём заявок",
    }
    m2 = FakeMessage(text="принимать заявки с сайта")
    await main.run_classify(m2, "принимать заявки с сайта")
    sent_text = fake_n8n.calls_of("classify")[-1][1][0]
    assert "нужен бот" in sent_text and "Дополнение:" in sent_text
    assert main.pending_get(500, 101) is None


async def test_run_classify_signature_failure_is_honest_error(fake_n8n):
    """S4: отказ подписи (ок:false) — честная ошибка, а не вечное уточнение."""
    fake_n8n.classify_result = {"ok": False, "error": "unauthorized: подпись не подтверждена"}
    m = FakeMessage(text="нужен бот")
    await main.run_classify(m, "нужен бот")
    assert "unauthorized" in m.sent[0].edits[0][0]
    assert main.pending_get(500, 101) is None  # уточнение НЕ поставлено


async def test_run_classify_lead_saved_false_without_clarify_is_error(fake_n8n):
    """S4: lead_saved:false без needs_clarification — ошибка, не цикл уточнений."""
    fake_n8n.classify_result = {"ok": True, "is_request": True, "lead_saved": False}
    m = FakeMessage(text="нужен бот")
    await main.run_classify(m, "нужен бот")
    assert "Не удалось сохранить заявку" in m.sent[0].edits[0][0]
    assert main.pending_get(500, 101) is None


async def test_run_classify_service_error_restores_pending(fake_n8n):
    main.pending_put(500, 101, "нужен бот")
    fake_n8n.errors["classify"] = N8nError("down")
    m = FakeMessage(text="принимать заявки")
    await main.run_classify(m, "принимать заявки")
    assert "недоступен" in m.sent[0].edits[0][0]
    assert main.pending_get(500, 101) == "нужен бот"  # уточнение не потеряно


async def test_run_classify_wait_edit_failure_falls_back_to_new_message(fake_n8n):
    """M5: сбой edit_text не оставляет вечный спиннер — текст уходит новым сообщением."""
    m = FakeMessage(text="нужен бот", fail_edit=True)
    await main.run_classify(m, "нужен бот")
    assert m.sent[0].answers, "должен быть запасной answer после сбоя edit_text"
    assert "Заявка сохранена" in m.sent[0].answers[0][0]


async def test_free_text_runs_classify(fake_n8n):
    m = FakeMessage(text="нужен бот", chat=FakeChat(type="private"))
    await main.free_text(m)
    assert fake_n8n.calls_of("classify")[0][1][0] == "нужен бот"


# ─────────────────────────────────── offer_consult / lc: ───────────────────────────────────
async def test_offer_consult_no_slots(fake_n8n):
    fake_n8n.slots_result = []
    m = FakeMessage()
    await main.offer_consult(m, "@alice", None)
    assert m.replies == []


async def test_offer_consult_slots_error_is_silent(fake_n8n):
    fake_n8n.errors["slots"] = N8nError("down")
    m = FakeMessage()
    await main.offer_consult(m, "@alice", None)
    assert m.replies == []


async def test_cb_lead_consult_skip(fake_n8n):
    q = FakeCallback("lc:skip")
    await main.cb_lead_consult(q)
    assert "менеджер" in q.message.edits[0][0]
    assert q.answered == 1


async def test_cb_lead_consult_books_and_writes_date_to_lead(fake_n8n):
    q = FakeCallback(f"lc:{SLOT['id']}:L7")
    await main.cb_lead_consult(q)
    assert "Консультация" in q.message.edits[0][0]
    assert fake_n8n.calls_of("book")[0][1] == (SLOT["id"], "@alice")
    ld = fake_n8n.calls_of("lead_date")[0][1]
    assert ld[0] == "@alice" and ld[2] == "L7"  # дата — в нужную заявку (M5)


async def test_cb_lead_consult_slot_taken(fake_n8n):
    fake_n8n.book_result = {"ok": False, "error": "слот занят"}
    q = FakeCallback(f"lc:{SLOT['id']}")
    await main.cb_lead_consult(q)
    assert "только что заняли" in q.message.edits[0][0]


async def test_cb_lead_consult_book_error(fake_n8n):
    fake_n8n.errors["book"] = N8nError("down")
    q = FakeCallback(f"lc:{SLOT['id']}")
    await main.cb_lead_consult(q)
    assert "недоступна" in q.message.edits[0][0]


async def test_cb_lead_consult_lead_date_failure_still_confirms(fake_n8n):
    fake_n8n.errors["lead_date"] = N8nError("down")
    q = FakeCallback(f"lc:{SLOT['id']}:L7")
    await main.cb_lead_consult(q)
    assert "Консультация" in q.message.edits[0][0]


# ─────────────────────────────────── helpers / entrypoint ───────────────────────────────────
async def test_btn_classify_hint(fake_n8n):
    m = FakeMessage()
    await main.btn_classify(m)
    assert "текст заявки" in m.replies[0][0]


async def test_safe_answer_swallows_errors(fake_n8n):
    class Boom(FakeMessage):
        async def answer(self, *a, **kw):
            raise RuntimeError("network")

    await main.safe_answer(Boom(), "текст")  # не падает


async def test_safe_edit_swallows_errors():
    class BoomMsg:
        async def edit_text(self, *a, **kw):
            raise RuntimeError("message is not modified")

    q = FakeCallback("book:x", message=BoomMsg())
    await main.safe_edit(q, "текст")  # не падает


def test_display_name_and_get_user_id():
    assert main.display_name(FakeUser(id=5, username="bob")) == "@bob"
    assert main.display_name(FakeUser(id=5, username=None)) == "5"
    assert main.display_name(None) == "?"
    assert main.get_user_id(FakeUser(id=9)) == 9
    assert main.get_user_id(None) == 0


def test_chat_lock_reuse_and_cap(monkeypatch):
    monkeypatch.setattr(main, "PENDING_MAX_CHATS", 2)
    main.CHAT_LOCKS.clear()
    a = main.chat_lock(1)
    assert main.chat_lock(1) is a  # один и тот же lock на чат
    for chat in range(2, 50):
        main.chat_lock(chat)  # превышение капы — словарь чистится
    assert len(main.CHAT_LOCKS) <= 3  # мягкая капа: не копим брошенные чаты


def test_main_exits_without_token(monkeypatch):
    monkeypatch.setattr(main, "BOT_TOKEN", "")
    with pytest.raises(SystemExit):
        import asyncio

        asyncio.run(main.main())


def test_main_exits_without_sign_secret(monkeypatch):
    monkeypatch.setattr(main, "BOT_TOKEN", "123:fake")
    monkeypatch.setattr(main, "DEMO_SIGN_SECRET", "")
    with pytest.raises(SystemExit):
        import asyncio

        asyncio.run(main.main())


def test_pending_cap_evicts_oldest(monkeypatch):
    monkeypatch.setattr(main, "PENDING_MAX_CHATS", 1)
    main.PENDING_CLARIFY.clear()
    main.pending_put(1, 1, "первая")
    main.pending_put(1, 2, "вторая")
    # кап 1: после второй записи остаётся только она (старая вытеснена)
    assert main.pending_get(1, 2) == "вторая"
    assert main.pending_get(1, 1) is None


async def test_safe_m_edit_both_paths_fail_swallows(fake_n8n):
    class DoubleFail(FakeSent):
        async def edit_text(self, *a, **kw):
            raise RuntimeError("edit down")

        async def answer(self, *a, **kw):
            raise RuntimeError("answer down")

    await main.safe_m_edit(DoubleFail(), "текст")  # не падает, только логирует


class _CmdArgs:
    def __init__(self, args):
        self.args = args
