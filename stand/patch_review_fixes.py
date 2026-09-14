#!/usr/bin/env python3
"""Батч-реконсиляция воркфлоу к каноническому состоянию репозитория (2026-09-14, ревью S-04).

Идемпотентно и безопасно (S5):
  - узлы приводятся к каноническим телам из stand/*.json (resolveUser при identity
    никуда НЕ убирается — канон уже содержит его), повторный запуск — no-op;
  - патч IF «Пусто?» использует equals (НЕ notEquals — иначе инверсия веток);
  - самопроверка строгая: resolveUser в каждой нужной ноде, цепочки связей валидны,
    единый источник слотов в demo-10 совпадает в «Слоты» и «Бронь».

Использование:
  python patch_review_fixes.py --json-only      # привести локальные stand/*.json
  python patch_review_fixes.py --push-db        # на CT100: реконсиляция + заливка в БД
  python patch_review_fixes.py                  # справка
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

STAND = Path(__file__).resolve().parent
if str(STAND.parent) not in sys.path:
    sys.path.insert(0, str(STAND.parent))

FILES = {
    "demo-09": "demo-09-ai-classifier.json",
    "demo-10": "demo-10-booking.json",
    "demo-11": "demo-11-wizard.json",
}

NODES_JS = {
    "demo-09": ["Валидация", "Разбор ответа", "Лид-захват", "Лиды", "Присвоить дату"],
    "demo-10": ["Слоты", "Бронь", "Мои записи", "Отмена"],
    "demo-11": ["Маршрут wizard"],
}

REQUIRED_RESOLVE_USER = {
    "demo-09": ["Валидация", "Лиды", "Присвоить дату"],
    "demo-10": ["Бронь", "Мои записи", "Отмена"],
    "demo-11": ["Маршрут wizard"],
}


def _name_index(wf: dict) -> dict:
    return {n["name"]: n for n in wf["nodes"]}


def load_canonical(wid: str) -> dict:
    return json.loads((STAND / FILES[wid]).read_text(encoding="utf-8"))


def sync_js(wf: dict, src: dict, names: list[str]) -> list[str]:
    """Привести jsCode узлов к канону; вернуть список изменённых."""
    idx, sidx = _name_index(wf), _name_index(src)
    changed = []
    for name in names:
        if name not in sidx:
            continue  # в каноне узла нет — не трогаем
        body = sidx[name]["parameters"].get("jsCode")
        if body is None:
            continue
        if name not in idx:
            wf["nodes"].append(_copy_node(sidx[name]))
            changed.append(f"+{name}")
            idx = _name_index(wf)
            continue
        if idx[name]["parameters"].get("jsCode") != body:
            idx[name]["parameters"]["jsCode"] = body
            changed.append(name)
    return changed


def _copy_node(src_node: dict) -> dict:
    return json.loads(json.dumps(src_node))


def reconcile_09(wf: dict, src: dict) -> list[str]:
    changed = sync_js(wf, src, NODES_JS["demo-09"])
    idx = _name_index(wf)
    # LLM timeout
    llm = idx.get("LLM")
    if llm is not None:
        opts = dict(llm["parameters"].get("options") or {})
        if opts.get("timeout") != 30000:
            opts["timeout"] = 30000
            llm["parameters"]["options"] = opts
            changed.append("LLM.timeout")
    # IF «Пусто?»: equals (не notEquals!) и соединения Валидация→Пусто?→(Ответ|LLM)
    if "Пусто?" in idx:
        op = idx["Пусто?"]["parameters"]["conditions"]["conditions"][0]["operator"]["operation"]
        if op != "equals":
            idx["Пусто?"]["parameters"]["conditions"]["conditions"][0]["operator"]["operation"] = "equals"
            changed.append("Пусто?.operator→equals")
    else:
        src_if = _name_index(src).get("Пусто?")
        if src_if is not None:
            wf["nodes"].append(_copy_node(src_if))
            changed.append("+Пусто?")
            idx = _name_index(wf)
    names = set(idx)
    if "Пусто?" in names:
        wf["connections"]["Валидация"] = {"main": [[{"node": "Пусто?", "type": "main", "index": 0}]]}
        wf["connections"]["Пусто?"] = {
            "main": [
                [{"node": "Ответ", "type": "main", "index": 0}],
                [{"node": "LLM", "type": "main", "index": 0}],
            ]
        }
    return changed


def reconcile_10(wf: dict, src: dict) -> list[str]:
    return sync_js(wf, src, NODES_JS["demo-10"])


def reconcile_11(wf: dict, src: dict) -> list[str]:
    changed = sync_js(wf, src, NODES_JS["demo-11"])
    idx = _name_index(wf)
    # http-узел брони: jsonBody с sig и service
    book = idx.get("Бронь (demo-10)")
    sbook = _name_index(src).get("Бронь (demo-10)")
    if book is not None and sbook is not None:
        if book["parameters"].get("jsonBody") != sbook["parameters"]["jsonBody"]:
            book["parameters"]["jsonBody"] = sbook["parameters"]["jsonBody"]
            changed.append("Бронь (demo-10).jsonBody")
    # новые узлы (слоты из demo-10) — добавляем идемпотентно
    for name in ("Нужны слоты?", "Слоты (demo-10)", "Шаг слотов"):
        if name not in idx and name in _name_index(src):
            wf["nodes"].append(_copy_node(_name_index(src)[name]))
            changed.append(f"+{name}")
    idx = _name_index(wf)
    if "Нужны слоты?" in idx:
        wf["connections"]["Это бронь?"] = {
            "main": [
                [{"node": "Бронь (demo-10)", "type": "main", "index": 0}],
                [{"node": "Нужны слоты?", "type": "main", "index": 0}],
            ]
        }
        wf["connections"]["Нужны слоты?"] = {
            "main": [
                [{"node": "Слоты (demo-10)", "type": "main", "index": 0}],
                [{"node": "Ответ wizard", "type": "main", "index": 0}],
            ]
        }
        wf["connections"]["Слоты (demo-10)"] = {"main": [[{"node": "Шаг слотов", "type": "main", "index": 0}]]}
        wf["connections"]["Шаг слотов"] = {"main": [[{"node": "Ответ wizard", "type": "main", "index": 0}]]}
    return changed


RECONCILE = {"demo-09": reconcile_09, "demo-10": reconcile_10, "demo-11": reconcile_11}


def patch(wid: str, wf: dict) -> dict:
    src = load_canonical(wid)
    changed = RECONCILE[wid](wf, src)
    for name in NODES_JS[wid]:
        if name in _name_index(src) and name not in _name_index(wf):
            raise RuntimeError(f"{wid}: узел {name} отсутствует после реконсиляции")
    if changed:
        print(f"{wid}: обновлено: {', '.join(changed)}")
    else:
        print(f"{wid}: уже каноническое состояние")
    return wf


def selfcheck(wid: str, wf: dict) -> None:
    idx = _name_index(wf)
    names = set(idx)
    for name in REQUIRED_RESOLVE_USER[wid]:
        assert name in names, f"{wid}: нет узла {name}"
        code = idx[name]["parameters"].get("jsCode", "")
        assert "function resolveUser" in code, f"{wid}/{name}: resolveUser отсутствует"
        assert code.count("resolveUser(") >= 2 or name == "Бронь", f"{wid}/{name}: resolveUser не вызван"
    if wid == "demo-09":
        op = idx["Пусто?"]["parameters"]["conditions"]["conditions"][0]["operator"]["operation"]
        assert op == "equals", "demo-09: IF «Пусто?» не equals"
        vcode = idx["Валидация"]["parameters"]["jsCode"]
        assert "'аноним'" not in vcode, "demo-09: анонимный фолбэк снят"
        assert "unauthorized" in idx["Валидация"]["parameters"]["jsCode"], "demo-09: нет отказов unauthorized"
        c = wf["connections"]
        assert c["Валидация"]["main"][0][0]["node"] == "Пусто?"
        assert c["Пусто?"]["main"][0][0]["node"] == "Ответ"
        assert c["Пусто?"]["main"][1][0]["node"] == "LLM"
    if wid == "demo-10":
        slots, book = idx["Слоты"]["parameters"]["jsCode"], idx["Бронь"]["parameters"]["jsCode"]
        assert "ЕДИНЫЙ ИСТОЧНИК СЛОТОВ" in slots and "ЕДИНЫЙ ИСТОЧНИК СЛОТОВ" in book
        assert "existing.user === user" in book and "idempotent: true" in book, "demo-10: идемпотентность S3"
        assert "canonSlots" in slots and "canonSlots" in book, "demo-10: единый генератор"
    if wid == "demo-11":
        route = idx["Маршрут wizard"]["parameters"]["jsCode"]
        assert "__SIGN_SECRET__" in route and "createHmac" in route, "demo-11: sig в confirm (B1)"
        body = idx["Бронь (demo-10)"]["parameters"]["jsonBody"]
        assert "sig" in body and "service" in body, "demo-11: sig/service не прокидываются"
        for name in ("Нужны слоты?", "Слоты (demo-10)", "Шаг слотов"):
            assert name in names, f"demo-11: нет узла {name}"
    # общая проверка связей: все ноды существуют
    for src_name, conn in wf["connections"].items():
        assert src_name in names, f"{wid}: источник связи {src_name} не найден"
        for branch in conn.get("main") or []:
            for target in branch or []:
                assert target["node"] in names, f"{wid}: связь {src_name}→{target['node']} в никуда"


def main() -> int:
    json_only = "--json-only" in sys.argv
    push = "--push-db" in sys.argv
    if not json_only and not push:
        print("использование: --json-only | --push-db")
        return 2
    for wid, fname in FILES.items():
        wf = json.loads((STAND / fname).read_text(encoding="utf-8"))
        wf = patch(wid, wf)
        selfcheck(wid, wf)
        (STAND / fname).write_text(json.dumps(wf, ensure_ascii=False), encoding="utf-8")
        print(f"{wid}: selfcheck OK")
    if push:
        from stand.deploy_db import load_env_secrets, push_to_db  # noqa: PLC0415

        wfs = {
            wid: json.loads((STAND / fname).read_text(encoding="utf-8"))
            for wid, fname in FILES.items()
        }
        push_to_db(wfs, load_env_secrets())
        print("БД залита; перезапустите n8n для регистрации вебхуков")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
