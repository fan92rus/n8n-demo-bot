"""Идемпотентность и безопасность патч-скриптов (S5).

Ключевое: повторный запуск не снимает identity и не инвертирует ветки IF,
самопроверка строгая (resolveUser в каждой нужной ноде).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from stand import patch_identity as pident
from stand import patch_review_fixes as prf

STAND = Path(__file__).resolve().parent.parent / "stand"
FILES = {
    "demo-09": "demo-09-ai-classifier.json",
    "demo-10": "demo-10-booking.json",
    "demo-11": "demo-11-wizard.json",
}


def load(wid: str) -> dict:
    return json.loads((STAND / FILES[wid]).read_text(encoding="utf-8"))


@pytest.mark.parametrize("wid", list(FILES))
def test_patch_review_fixes_is_idempotent(wid):
    wf = load(wid)
    before = json.dumps(wf, ensure_ascii=False)
    out = prf.patch(wid, wf)
    after = json.dumps(out, ensure_ascii=False)
    assert after == before, f"{wid}: patch_review_fixes изменил канонический файл"
    prf.selfcheck(wid, out)


def test_patch_review_fixes_restores_resolve_user_that_would_be_stripped():
    """Симуляция старого сценария S5: Бронь без identity -> патч НЕ снимает её."""
    wf = load("demo-10")
    nodes = {n["name"]: n for n in wf["nodes"]}
    # «сломали» identity так же, как старый VALIDATE_09/BOCK_10: убрали resolveUser
    code = nodes["Бронь"]["parameters"]["jsCode"]
    stripped = code[code.index("function resolveUser") : code.index("}\n", code.index("function resolveUser")) + 2]
    nodes["Бронь"]["parameters"]["jsCode"] = code.replace(stripped, "")
    prf.patch("demo-10", wf)
    after = nodes["Бронь"]["parameters"]["jsCode"]
    assert "function resolveUser" in after, "патч не восстановил resolveUser в Бронь"
    assert "existing.user === user" in after, "идемпотентность S3 не потеряна"


def test_patch_review_fixes_corrects_not_equals_if():
    wf = load("demo-09")
    op_node = next(n for n in wf["nodes"] if n["name"] == "Пусто?")
    op_node["parameters"]["conditions"]["conditions"][0]["operator"]["operation"] = "notEquals"
    prf.patch("demo-09", wf)
    op = op_node["parameters"]["conditions"]["conditions"][0]["operator"]["operation"]
    assert op == "equals", "patch_review_fixes обязан вернуть equals"


@pytest.mark.parametrize("wid", list(FILES))
def test_patch_identity_is_idempotent(wid):
    wf = load(wid)
    before = json.dumps(wf, ensure_ascii=False)
    out = copy.deepcopy(wf)
    changes = pident.patch_workflow(wid, out)
    assert changes == [], f"{wid}: канон должен быть уже пропатчен ({changes})"
    pident.selfcheck(wid, out)
    assert json.dumps(out, ensure_ascii=False) == before


def test_patch_identity_migrates_old_anonymous_state():
    """Старое состояние (без identity) за один прогон приводится к канону, повтор — no-op."""
    wf = {
        "id": "demo-09",
        "nodes": [
            {"name": "Валидация", "parameters": {
                "jsCode": "const body = $input.first().json.body || {};\n"
                          "return [{ json: { text, user: String(body.user || 'аноним').slice(0, 64) } }];"}},
            {"name": "Лид-захват", "parameters": {
                "jsCode": "const src = $('Валидация').first().json;"}},
            {"name": "Лиды", "parameters": {
                "jsCode": "const user = (($('Webhook leads').first().json.body) || {}).user || '';"}},
            {"name": "Присвоить дату", "parameters": {
                "jsCode": "const user = String(body.user || '');"}},
        ],
        "connections": {},
    }
    run1 = pident.patch_workflow("demo-09", wf)
    assert run1, "из старого состояния должны быть изменения"
    pident.selfcheck("demo-09", wf)
    snap = json.dumps(wf, ensure_ascii=False)
    run2 = pident.patch_workflow("demo-09", wf)
    assert run2 == [], "повторный прогон должен быть no-op"
    assert json.dumps(wf, ensure_ascii=False) == snap
