# Интеграционный e2e-набор демо-стенда n8n (живые webhooks, не моки).
# Запуск: python3 stand/test_integration.py [BASE_URL]
#   BASE_URL по умолчанию https://funnyhome.netcraze.pro
# Требует живого стенда (CT100). Кодирует воронку: слоты -> бронь -> мои ->
# отмена -> заявка (ясная/туманная/болтовня) -> дата -> лиды.
# Выход: 0 = все проверки прошли, 1 = есть провалы (для CI).
import hashlib
import hmac
import json
import os
import sys
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "https://funnyhome.netcraze.pro"
USER = "@e2e_test_agent"
OTHER = "@e2e_other"
SECRET = os.environ.get("DEMO_SIGN_SECRET", "")
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


def check(name: str, cond: bool, detail: str = "") -> None:
    (passed if cond else failed).append(name)
    print(("  OK  " if cond else "FAIL  ") + name + (f"  [{detail}]" if detail and not cond else ""))


print("== 1. Слоты и бронирование ==")
slots = post("/demo/slots", {})
noforgery = post("/demo/book", {"slot_id": slots["slots"][0]["id"], "user": USER}, sign=False)
check("identity: подделка без подписи отклонена", noforgery.get("ok") is False and "unauth" in str(noforgery.get("error", "")), str(noforgery))
check("slots: ok + список", slots.get("ok") is True and isinstance(slots.get("slots"), list) and len(slots["slots"]) > 0)
slot = slots["slots"][0]["id"]
book = post("/demo/book", {"slot_id": slot, "user": USER})
check("book: успешная бронь", book.get("ok") is True, json.dumps(book, ensure_ascii=False)[:120])
book2 = post("/demo/book", {"slot_id": slot, "user": OTHER})
check("book: повторная бронь отклонена", book2.get("ok") is False, json.dumps(book2, ensure_ascii=False)[:120])
book3 = post("/demo/book", {"slot_id": "2099-99-99-9999", "user": USER})
check("book: несуществующий слот отклонён", book3.get("ok") is False)
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
clear = post("/demo/classify", {"text": "Нужен телеграм-бот для приёма заявок с сайта и записи их в Google-таблицу, с уведомлением менеджеру", "user": USER})
check("classify: ясная заявка сохранена", clear.get("lead_saved") is True and clear.get("needs_clarification") is False, json.dumps(clear, ensure_ascii=False)[:200])

print("== 4. Дата консультации и лиды ==")
SRC = "Нужен телеграм-бот для приёма заявок с сайта и записи их в Google-таблицу, с уведомлением менеджеру"
DATE = "консультация e2e 21.09 10:00"
ld = post("/demo/lead_date", {"user": USER, "date": DATE})
check("lead_date: дата записана", ld.get("ok") is True, json.dumps(ld, ensure_ascii=False)[:150])
leads = post("/demo/leads", {"user": USER})
own = [l for l in leads.get("leads", []) if l.get("user") == USER]
check("leads: заявка видна владельцу", len(own) >= 1)
if own:
    top = own[-1]
    check("leads: исходный текст сохранён", top.get("source_msg") == SRC, repr(top.get("source_msg"))[:120])
    check("leads: дата в заявке", top.get("date") == DATE, repr(top.get("date")))
    check("leads: summary заполнено", bool(top.get("summary")))
leads_o = post("/demo/leads", {"user": OTHER})
check("leads: приватность — чужие не видны", all(l.get("user") != USER for l in leads_o.get("leads", [])))

print("== 5. Wizard ==")
w1 = post("/demo/wizard", {"sel": "start"})
check("wizard: старт отдаёт кнопки", bool(w1.get("buttons")), json.dumps(w1, ensure_ascii=False)[:150])

print(f"\nИтог: {len(passed)} OK, {len(failed)} FAIL")
if failed:
    print("Провалы:", ", ".join(failed))
    sys.exit(1)
