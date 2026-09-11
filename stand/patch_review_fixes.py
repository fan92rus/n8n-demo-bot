#!/usr/bin/env python3
"""Батч 2 фиксов по ревью (2026-09-12): demo-09/10/11.

demo-09:
  - Валидация: пустой/битый text не throw (HTTP 500), а ok:false; user ограничен 64.
  - Новый узел IF «Пусто?»: пустой текст идёт straight на Ответ (LLM не тратится).
  - Разбор ответа: срез ```-фенсов, строгая нормализация is_request/needs_clarification,
    безопасный fallback (is_request:false вместо мусорного лида).
  - LLM: options.timeout 30s.
demo-10:
  - Слоты: 12 рабочих дней (24 слота) вместо 6; барнаульская дата (+7ч к базе);
    prune прошедших броней.
  - Бронь: тот же +7ч сдвиг и prune.
demo-11:
  - genSlots: тот же +7h сдвиг; витрина слотов ограничена 12 (6 дней).
  - confirm: реальный user из body.user (fallback wizard-demo).
  - Бронь (demo-10): localhost -> 192.168.1.111.

Использование: python patch_review_fixes.py --json-only  # правит локальные stand/*.json
На CT100 импортируют patch() и применяют к живому JSON из БД (учётные данные не трогаются).
Идемпотентно: наличие узла «Пусто?» и новые тела кода не применяются повторно.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

STAND = Path(__file__).resolve().parent

SLOTS_10 = """// Генерируем слоты на 12 рабочих дней вперёд (10:00 и 14:00), вычитаем занятые.
// Барнаул = UTC+7: сдвигаем базу на +7ч и работаем в UTC-геттерах (календарь совпадает).
const staticData = $getWorkflowStaticData('global');
staticData.bookings = staticData.bookings || {};
const booked = staticData.bookings;
const slots = [];
const today = new Date(Date.now() + 7 * 3600 * 1000).toISOString().slice(0, 10);
for (const k of Object.keys(booked)) {
  if (k.slice(0, 10) < today) delete booked[k];
}
let d = new Date(Date.now() + 7 * 3600 * 1000);
while (slots.length < 24) {
  d.setDate(d.getDate() + 1);
  const dow = d.getDay();
  if (dow === 0 || dow === 6) continue;
  const day = d.toISOString().slice(0, 10);
  for (const [h, label] of [['10:00', 'утро'], ['14:00', 'день']]) {
    const id = day + '-' + h.replace(':', '');
    if (booked[id]) continue;
    slots.push({ id, label, start: day + ' ' + h + ' (' + label + ')', tz: 'Asia/Barnaul' });
  }
}
return [{ json: { ok: true, slots } }];"""

BOOK_10 = """// Бронь слота: слот обязан существовать в генерации (та же логика, что в ветке слотов), потом проверка занятости.
// Барнаул = UTC+7: сдвигаем базу на +7ч (как в «Слоты»), прошлые брони подчищаем.
const staticData = $getWorkflowStaticData('global');
staticData.bookings = staticData.bookings || {};
const body = $input.first().json.body || {};
const slotId = String(body.slot_id || '');
const user = String(body.user || 'unknown').slice(0, 64);
const today = new Date(Date.now() + 7 * 3600 * 1000).toISOString().slice(0, 10);
for (const k of Object.keys(staticData.bookings)) {
  if (k.slice(0, 10) < today) delete staticData.bookings[k];
}
const valid = {};
const d = new Date(Date.now() + 7 * 3600 * 1000);
let made = 0;
while (made < 12) {
  d.setDate(d.getDate() + 1);
  const dow = d.getDay();
  if (dow === 0 || dow === 6) continue;
  const day = d.toISOString().slice(0, 10);
  for (const [h, label] of [['10:00', 'утро'], ['14:00', 'день']]) {
    valid[day + '-' + h.replace(':', '')] = day + ' ' + h + ' (' + label + ')';
  }
  made += 1;
}
if (!valid[slotId]) {
  return [{ json: { ok: false, error: 'слот не найден — запросите /slots' } }];
}
if (staticData.bookings[slotId]) {
  return [{ json: { ok: false, error: 'слот уже занят' } }];
}
staticData.bookings[slotId] = { user, at: new Date().toISOString() };
const day = slotId.slice(0, 10);
const hh = slotId.slice(11, 13) + ':' + slotId.slice(13, 15);
return [{ json: { ok: true, booking: { slot_id: slotId, label: day, start: day + ' ' + hh, user } } }];"""

VALIDATE_09 = """const body = $input.first().json.body || {};
const text = String(body.text || '').slice(0, 2000);
if (!text.trim()) {
  // пустой текст — честный ответ вместо HTTP 500
  return [{ json: { ok: false, error: 'Опишите задачу — отправьте текст заявки' } }];
}
return [{ json: { text, user: String(body.user || 'аноним').slice(0, 64) } }];"""

PARSE_09 = """const r = $input.first().json;
let content = '';
try { content = String(r.choices[0].message.content || ''); } catch (e) {}
// LLM любит заворачивать JSON в ```-фенсы — срезаем
content = content.replace(/^```(?:json)?\\s*/i, '').replace(/```\\s*$/, '').trim();
let parsed = null;
try { parsed = JSON.parse(content); } catch (e) {}
if (!parsed || typeof parsed !== 'object') {
  // не ломаемся в мусорный лид: безопасный «не заявка» с подсказкой
  return [{ json: { ok: true, category: 'прочее', priority: 'средний',
    summary: 'не удалось разобрать ответ модели — попробуйте переформулировать',
    is_request: false, needs_clarification: false, clarify_question: '', lead_saved: false } }];
}
parsed.is_request = parsed.is_request === true || parsed.is_request === 'true';
parsed.needs_clarification = parsed.needs_clarification === true || parsed.needs_clarification === 'true';
parsed.clarify_question = String(parsed.clarify_question || '');
return [{ json: { ok: true, ...parsed } }];"""

IF_EMPTY = {
    "parameters": {
        "conditions": {
            "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose"},
            "conditions": [
                {
                    "leftValue": "={{ String($json.ok === false) }}",
                    "rightValue": "true",
                    "operator": {"type": "string", "operation": "notEquals"},
                }
            ],
            "combinator": "and",
        },
        "options": {},
    },
    "type": "n8n-nodes-base.if",
    "typeVersion": 2,
    "position": [340, 0],
    "id": "if-empty-09",
    "name": "Пусто?",
}


def patch_09(wf: dict) -> dict:
    nodes = {n["name"]: n for n in wf["nodes"]}
    nodes["Валидация"]["parameters"]["jsCode"] = VALIDATE_09
    nodes["Разбор ответа"]["parameters"]["jsCode"] = PARSE_09
    llm = nodes["LLM"]["parameters"]
    opts = llm.get("options") or {}
    if not opts.get("timeout"):
        opts["timeout"] = 30000
        llm["options"] = opts
    names = [n["name"] for n in wf["nodes"]]
    if "Пусто?" not in names:
        wf["nodes"].append(dict(IF_EMPTY))
        # перепрошивка цепочки: Валидация -> Пусто?; true -> Ответ; false -> LLM
        wf["connections"]["Валидация"] = {"main": [[{"node": "Пусто?", "type": "main", "index": 0}]]}
        wf["connections"]["Пусто?"] = {
            "main": [
                [{"node": "Ответ", "type": "main", "index": 0}],
                [{"node": "LLM", "type": "main", "index": 0}],
            ]
        }
    return wf


def patch_10(wf: dict) -> dict:
    nodes = {n["name"]: n for n in wf["nodes"]}
    nodes["Слоты"]["parameters"]["jsCode"] = SLOTS_10
    nodes["Бронь"]["parameters"]["jsCode"] = BOOK_10
    return wf


def patch_11(wf: dict) -> dict:
    nodes = {n["name"]: n for n in wf["nodes"]}
    route = nodes["Маршрут wizard"]
    code = route["parameters"]["jsCode"]
    if "Date.now() + 7 * 3600" not in code:
        code = code.replace(
            "  const valid = [];\n  const d = new Date();",
            "  const valid = [];\n  const d = new Date(Date.now() + 7 * 3600 * 1000);",
        )
    if "genSlots().slice(0, 12)" not in code:
        code = code.replace("const slots = genSlots();", "const slots = genSlots().slice(0, 12);")
    if "body.user" not in code:
        old = "out = { stage: 'book', slot_id: slotId, user: 'wizard-demo (' + (services[svc] || svc) + ')' };"
        new = (
            "const u = String(body.user || '').trim().slice(0, 64);\n"
            "  out = { stage: 'book', slot_id: slotId, user: u || ('wizard-demo (' + (services[svc] || svc) + ')') };"
        )
        code = code.replace(old, new)
    route["parameters"]["jsCode"] = code
    book = nodes["Бронь (demo-10)"]["parameters"]
    if "localhost:5678" in str(book.get("url", "")):
        book["url"] = str(book["url"]).replace("http://localhost:5678", "http://192.168.1.111:5678")
    return wf


def patch(wid: str, wf: dict) -> dict:
    if wid == "demo-09":
        return patch_09(wf)
    if wid == "demo-10":
        return patch_10(wf)
    if wid == "demo-11":
        return patch_11(wf)
    raise SystemExit(f"unknown workflow id: {wid}")


def main() -> None:
    files = {
        "demo-09": STAND / "demo-09-ai-classifier.json",
        "demo-10": STAND / "demo-10-booking.json",
        "demo-11": STAND / "demo-11-wizard.json",
    }
    for wid, path in files.items():
        wf = json.loads(path.read_text(encoding="utf-8"))
        wf = patch(wid, wf)
        path.write_text(json.dumps(wf, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"patched {wid} -> {path.name}")
    # само-проверки
    wf09 = json.loads(files["demo-09"].read_text(encoding="utf-8"))
    names = [n["name"] for n in wf09["nodes"]]
    assert "Пусто?" in names and "throw new Error" not in json.dumps(wf09["nodes"], ensure_ascii=False)
    c = wf09["connections"]
    assert c["Пусто?"]["main"][0][0]["node"] == "Ответ" and c["Пусто?"]["main"][1][0]["node"] == "LLM"
    wf10 = json.loads(files["demo-10"].read_text(encoding="utf-8"))
    assert "length < 24" in json.dumps(wf10["nodes"], ensure_ascii=False)
    wf11 = json.loads(files["demo-11"].read_text(encoding="utf-8"))
    s = json.dumps(wf11["nodes"], ensure_ascii=False)
    assert "body.user" in s and "localhost:5678" not in s
    print("asserts OK")


if __name__ == "__main__":
    if "--json-only" in sys.argv:
        main()
    else:
        print("import patch() for DB-side use")
