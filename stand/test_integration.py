# Интеграционный e2e-набор демо-стенда n8n (живые webhooks, не моки).
# Запуск на CT100 из корня репо:
#   DEMO_SIGN_SECRET="$(grep DEMO_SIGN_SECRET /root/n8n-demo-bot.env | cut -d= -f2)" \
#   BOT_TOKEN="$(grep BOT_TOKEN /root/n8n-demo-bot.env | cut -d= -f2)" \
#   python3 stand/test_integration.py [BASE_URL]
#   BASE_URL по умолчанию https://funnyhome.netcraze.pro
# Кодирует воронку: слоты -> бронь (включая путь confirm визарда) -> мои ->
# отмена -> заявка (ясная/туманная/болтовня) -> дата -> лиды -> мини-апп (initData).
# Выход: 0 = все проверки прошли, 1 = есть провалы (для CI).
# Секреты в вывод НЕ печатаются.
import hashlib
import hmac
import json
import os
import sys
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "https://funnyhome.netcraze.pro"
USER = "@e2e_test_agent"
OTHER = "@e2e_other"
MINI_USER = "mini_e2e"
SECRET = os.environ.get("DEMO_SIGN_SECRET", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
assert SECRET, "нужен env DEMO_SIGN_SECRET (identity обязательна на стенде)"
passed, failed = [], []


def post(path: str, payload: dict, sign: bool = True) -> dict:
    if sign and SECRET and payload.get("user"):
        payload = dict(payload)
        payload["sig"] = hmac.new(SECRET.encode(), str(payload["user"]).encode(), hashlib.sha256).hexdigest()
    req = urllib.request.Request(
        BASE + "/webhook" + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {"http_error": e.code}


def make_init_data(token: str, user_id: int, username: str) -> str:
    """Подписанная строка initData, которую шлёт мини-апп (raw-значения, '&').

    Алгоритм совпадает с resolveUser() в воркфлоу (проверен против реальной
    строки Telegram в ревью): data_check_string = sorted k=v joined '&'.
    """
    from urllib.parse import quote

    user = json.dumps(
        {"id": user_id, "username": username, "first_name": "E2E"},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    pairs = [("auth_date", "1726000000"), ("user", quote(user, safe=""))]
    dcs = "&".join(f"{k}={v}" for k, v in sorted(pairs))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    h = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    return dcs + "&hash=" + h


def check(name: str, cond: bool, detail: str = "") -> None:
    (passed if cond else failed).append(name)
    print(("  OK  " if cond else "FAIL  ") + name + (f"  [{detail}]" if detail and not cond else ""))


created_slots: list[dict] = []  # слоты, которые e2e обязан отменить в финале


def note_slot(slot_id: str, cancel_payload: dict | None = None) -> None:
    """Запомнить слот для уборки; cancel_payload — чем его снять (по умолчанию user USER)."""
    created_slots.append({"slot_id": slot_id, "payload": cancel_payload or {"slot_id": slot_id, "user": USER}, "sign": cancel_payload is None})


print("== 1. Слоты и бронирование ==")
slots = post("/demo/slots", {})
noforgery = post("/demo/book", {"slot_id": slots["slots"][0]["id"], "user": USER}, sign=False)
check("identity: подделка без подписи отклонена", noforgery.get("ok") is False and "unauth" in str(noforgery.get("error", "")), str(noforgery))
check("slots: ok + список", slots.get("ok") is True and isinstance(slots.get("slots"), list) and len(slots["slots"]) > 0)
slot = slots["slots"][0]["id"]
book = post("/demo/book", {"slot_id": slot, "user": USER})
check("book: успешная бронь", book.get("ok") is True, json.dumps(book, ensure_ascii=False)[:120])
book2 = post("/demo/book", {"slot_id": slot, "user": OTHER})
check("book: повторная бронь другим отклонена", book2.get("ok") is False, json.dumps(book2, ensure_ascii=False)[:120])
book3 = post("/demo/book", {"slot_id": "2099-99-99-9999", "user": USER})
check("book: несуществующий слот отклонён", book3.get("ok") is False)
book_again = post("/demo/book", {"slot_id": slot, "user": USER})
check("book: повторная бронь ТЕМ ЖЕ пользователем идемпотентна", book_again.get("ok") is True, json.dumps(book_again, ensure_ascii=False)[:120])
mine = post("/demo/my", {"user": USER})
check("my: бронь видна владельцу", any(b["slot_id"] == slot for b in mine.get("bookings", [])), json.dumps(mine, ensure_ascii=False)[:150])
mine_o = post("/demo/my", {"user": OTHER})
check("my: чужая бронь не видна", all(b["slot_id"] != slot for b in mine_o.get("bookings", [])))
slots2 = post("/demo/slots", {})
check("slots: занятый слот исчез", all(s["id"] != slot for s in slots2.get("slots", [])))

print("== 2. Отмена ==")
cancel_o = post("/demo/cancel", {"slot_id": slot, "user": OTHER})
check("cancel: чужую бронь отменить нельзя", cancel_o.get("ok") is False, json.dumps(cancel_o, ensure_ascii=False)[:120])
cancel = post("/demo/cancel", {"slot_id": slot, "user": USER})
check("cancel: своя бронь отменяется", cancel.get("ok") is True, json.dumps(cancel, ensure_ascii=False)[:120])
slots3 = post("/demo/slots", {})
check("slots: слот вернулся после отмены", any(s["id"] == slot for s in slots3.get("slots", [])))
mine2 = post("/demo/my", {"user": USER})
check("my: после отмены пусто", all(b["slot_id"] != slot for b in mine2.get("bookings", [])))

print("== 3. Заявки: болтовня / туман / ясная ==")
chat = post("/demo/classify", {"text": "привет, как дела?", "user": USER})
check("classify: болтовня не заявка", chat.get("is_request") is False and chat.get("lead_saved") is False)
vague = post("/demo/classify", {"text": "нужен бот", "user": USER})
check("classify: туманная требует уточнения", vague.get("needs_clarification") is True and bool(vague.get("clarify_question")) and vague.get("lead_saved") is False, json.dumps(vague, ensure_ascii=False)[:200])
SRC = "Нужен телеграм-бот для приёма заявок с сайта и записи их в Google-таблицу, с уведомлением менеджеру"
clear = post("/demo/classify", {"text": SRC, "user": USER})
check("classify: ясная заявка сохранена", clear.get("lead_saved") is True and clear.get("needs_clarification") is False, json.dumps(clear, ensure_ascii=False)[:200])
lead_id = clear.get("lead_id")
check("classify: выдан lead_id", bool(lead_id), repr(lead_id))

print("== 4. Дата консультации и лиды ==")
DATE = "консультация e2e 21.09 10:00"
ld = post("/demo/lead_date", {"user": USER, "date": DATE, "lead_id": lead_id})
check("lead_date: дата записана по lead_id", ld.get("ok") is True, json.dumps(ld, ensure_ascii=False)[:150])
leads = post("/demo/leads", {"user": USER})
own = [lead for lead in leads.get("leads", []) if lead.get("user") == USER]
check("leads: заявка видна владельцу", len(own) >= 1)
target = next((lead for lead in own if lead.get("id") == lead_id), None)
check("leads: дата в правильной заявке (M5)", target is not None and target.get("date") == DATE, repr(target))
if own:
    top = own[-1]
    check("leads: исходный текст сохранён", top.get("source_msg") == SRC, repr(top.get("source_msg"))[:120])
leads_o = post("/demo/leads", {"user": OTHER})
check("leads: приватность — чужие не видны", all(lead.get("user") != USER for lead in leads_o.get("leads", [])))

print("== 5. Wizard ==")
w1 = post("/demo/wizard", {"sel": "start"})
check("wizard: старт отдаёт кнопки", bool(w1.get("buttons")), json.dumps(w1, ensure_ascii=False)[:150])
w2 = post("/demo/wizard", {"sel": "srv:consult", "user": USER})
w2_ptrn = json.dumps(w2, ensure_ascii=False)[:200]
check("wizard: шаг слотов берёт свободные из demo-10", (w2.get("text") or "").startswith("Услуга: Консультация"), w2_ptrn)
wizard_slot_ids = []
for row in w2.get("buttons") or []:
    for b in row:
        cb = (b or {}).get("callback_data", "")
        if cb.startswith("wz:time:"):
            wizard_slot_ids.append(cb.split(":")[2])  # wz:time:<slot>:<svc>
check("wizard: шаг слотов непустой", len(wizard_slot_ids) > 0)

# B1: путь confirm визарда живой — бронь по кнопке «✅ Записаться»
wslot = wizard_slot_ids[0]
wbook = post("/demo/wizard", {"sel": f"confirm:{wslot}:consult", "user": USER})
wbook_txt = json.dumps(wbook, ensure_ascii=False)
check("wizard confirm: создаёт бронь", wbook.get("ok") is True or "Вы записаны" in wbook.get("text", ""), wbook_txt[:150])
note_slot(wslot)
wbook2 = post("/demo/wizard", {"sel": f"confirm:{wslot}:consult", "user": USER})
check("wizard confirm: повторная бронь тем же пользователем идемпотентна", wbook2.get("ok") is True or "Вы записаны" in wbook2.get("text", ""), json.dumps(wbook2, ensure_ascii=False)[:150])
wmine = post("/demo/my", {"user": USER})
check("wizard confirm: бронь видна в /my", any(b["slot_id"] == wslot for b in wmine.get("bookings", [])))
wslots = post("/demo/slots", {})
check("wizard confirm: занятый слот пропал из /slots", all(s["id"] != wslot for s in wslots.get("slots", [])))
w3 = post("/demo/wizard", {"sel": "srv:consult", "user": USER})
w3_offered = []
for row in w3.get("buttons") or []:
    for b in row:
        cb = (b or {}).get("callback_data", "")
        if cb.startswith("wz:time:"):
            w3_offered.append(cb.split(":")[2])
check("wizard: занятый слот НЕ предлагается (S2)", wslot not in w3_offered, w3_offered[:10])

print("== 6. Мини-апп (initData-identity) ==")
if not BOT_TOKEN:
    print("  SKIP: BOT_TOKEN не задан в окружении (нужен для initData-пути)")
else:
    mini = "@" + MINI_USER
    init_data = make_init_data(BOT_TOKEN, 777000555, MINI_USER)
    free = post("/demo/slots", {})
    mslot = free["slots"][0]["id"]
    m_book = post("/demo/book", {"slot_id": mslot, "init_data": init_data}, sign=False)
    check("miniapp: бронь через initData принята", m_book.get("ok") is True, json.dumps(m_book, ensure_ascii=False)[:150])
    note_slot(mslot, {"slot_id": mslot, "init_data": init_data})
    m_my = post("/demo/my", {"init_data": init_data}, sign=False)
    check("miniapp: бронь видна в «Моих записях»", any(b["slot_id"] == mslot for b in m_my.get("bookings", [])), json.dumps(m_my, ensure_ascii=False)[:150])
    m_cancel = post("/demo/cancel", {"slot_id": mslot, "init_data": init_data}, sign=False)
    check("miniapp: отмена своей брони работает", m_cancel.get("ok") is True, json.dumps(m_cancel, ensure_ascii=False)[:150])
    m_my2 = post("/demo/my", {"init_data": init_data}, sign=False)
    check("miniapp: после отмены брони нет", all(b["slot_id"] != mslot for b in m_my2.get("bookings", [])))

print(f"\nИтог: {len(passed)} OK, {len(failed)} FAIL")
if failed:
    print("Провалы:", ", ".join(failed))

# Уборка: снимаем всё, что создали (слоты должны вернуться в /slots)
for entry in created_slots:
    try:
        post("/demo/cancel", entry["payload"], sign=entry["sign"])
    except Exception:
        pass

if failed:
    sys.exit(1)
