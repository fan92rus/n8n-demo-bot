"""Инварианты воркфлоу n8n: единый источник слотов, подпись визарда (B1),
идемпотентность брони (S3), lead_id (M5), identity во всех нужных нодах.

Это регресс-защита от повторения блокера B1 и серии S1-S5 прямо на уровне JSON.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

STAND = Path(__file__).resolve().parent.parent / "stand"
FILES = {
    "demo-09": "demo-09-ai-classifier.json",
    "demo-10": "demo-10-booking.json",
    "demo-11": "demo-11-wizard.json",
}
CANON_BEGIN = "// === ЕДИНЫЙ ИСТОЧНИК СЛОТОВ"
CANON_END = "// === КОНЕЦ ЕДИНОГО ИСТОЧНИКА ==="
REQUIRED_RESOLVE_USER = {
    "demo-09": ["Валидация", "Лиды", "Присвоить дату"],
    "demo-10": ["Бронь", "Мои записи", "Отмена"],
    "demo-11": ["Маршрут wizard"],
}


@pytest.fixture(scope="module")
def wfs():
    return {
        wid: json.loads((STAND / fname).read_text(encoding="utf-8"))
        for wid, fname in FILES.items()
    }


def node(wf, name):
    for n in wf["nodes"]:
        if n["name"] == name:
            return n
    raise AssertionError(f"нет узла {name!r}")


def canon_block(code: str) -> str:
    assert CANON_BEGIN in code and CANON_END in code, "нет блока единого источника"
    return code[code.index(CANON_BEGIN) : code.index(CANON_END) + len(CANON_END)]


# ────────────────────────────── S1: единый источник слотов ──────────────────────────────
def test_slots_and_book_share_identical_canon_block(wfs):
    slots = canon_block(node(wfs["demo-10"], "Слоты")["parameters"]["jsCode"])
    book = canon_block(node(wfs["demo-10"], "Бронь")["parameters"]["jsCode"])
    assert slots == book, "«Слоты» и «Бронь» разошлись — слоты из /slots нельзя забронировать"
    assert "SLOT_DAYS = 12" in slots and "'10:00'" in slots and "'14:00'" in slots


def test_slots_endpoint_returns_only_free_slots(wfs):
    code = node(wfs["demo-10"], "Слоты")["parameters"]["jsCode"]
    assert "canonSlots(staticData.bookings)" in code
    assert ".filter((s) => !s.booked)" in code, "занятые слоты не должны предлагаться"


def test_book_validates_against_canon_window(wfs):
    code = node(wfs["demo-10"], "Бронь")["parameters"]["jsCode"]
    assert "canonSlots(staticData.bookings).some((s) => s.id === slotId)" in code
    assert "слот не найден" in code


# ────────────────────────────── S3: идемпотентность брони ──────────────────────────────
def test_book_is_idempotent_for_same_user(wfs):
    code = node(wfs["demo-10"], "Бронь")["parameters"]["jsCode"]
    assert "existing.user === user" in code
    assert "idempotent: true" in code, "повторная бронь тем же пользователем — успех"
    assert "слот занят другим пользователем" in code


def test_book_persists_service(wfs):
    code = node(wfs["demo-10"], "Бронь")["parameters"]["jsCode"]
    assert "body.service" in code and "svc" in code, "выбор услуги не декоративный"


# ────────────────────────────── B1: подпись в визарде ──────────────────────────────
def test_wizard_confirm_computes_signature(wfs):
    code = node(wfs["demo-11"], "Маршрут wizard")["parameters"]["jsCode"]
    assert "createHmac('sha256', '__SIGN_SECRET__')" in code, "visor confirm должен подписывать user"
    assert "sig" in code and "stage: 'book'" in code


def test_wizard_book_node_forwards_sig_and_service(wfs):
    body = node(wfs["demo-11"], "Бронь (demo-10)")["parameters"]["jsonBody"]
    assert "sig: $json.sig" in body, "B1: demo-10 требует валидную sig"
    assert "service: $json.svc" in body


def test_wizard_takes_slots_from_demo10(wfs):
    wf = wfs["demo-11"]
    assert node(wf, "Слоты (demo-10)")["parameters"]["url"].endswith("/webhook/demo/slots")
    assert "genSlots" not in node(wf, "Маршрут wizard")["parameters"]["jsCode"], (
        "визард не должен сам генерировать слоты (S2)"
    )
    assert "$('Маршрут wizard')" in node(wf, "Шаг слотов")["parameters"]["jsCode"]
    chan = wf["connections"]["Это бронь?"]["main"][1][0]["node"]
    assert chan == "Нужны слоты?", "не-бронь ветка должна уходить в ветку слотов"


# ────────────────────────────── S4 / M5: demo-09 ──────────────────────────────
def test_classifier_fails_fast_on_bad_signature(wfs):
    code = node(wfs["demo-09"], "Валидация")["parameters"]["jsCode"]
    assert "'unauthorized" in code, "нет подписи — честный отказ, не анонимный лид"
    assert "'аноним'" not in code


def test_if_empty_uses_equals_and_right_branch(wfs):
    wf = wfs["demo-09"]
    cond = node(wf, "Пусто?")["parameters"]["conditions"]["conditions"][0]
    assert cond["operator"]["operation"] == "equals", "notEquals инвертирует ветки"
    c = wf["connections"]
    assert c["Валидация"]["main"][0][0]["node"] == "Пусто?"
    assert c["Пусто?"]["main"][0][0]["node"] == "Ответ"
    assert c["Пусто?"]["main"][1][0]["node"] == "LLM"


def test_lead_capture_returns_lead_id(wfs):
    code = node(wfs["demo-09"], "Лид-захват")["parameters"]["jsCode"]
    assert "leadSeq" in code and "lead_id: lead.id" in code


def test_lead_date_targets_explicit_lead(wfs):
    code = node(wfs["demo-09"], "Присвоить дату")["parameters"]["jsCode"]
    assert "body.lead_id" in code and "x.id === leadId" in code, "M5: атрибуция по lead_id"
    assert "последняя открытая" in code  # фолбэк для старых заявок


# ────────────────────────────── identity + целостность ──────────────────────────────
def test_resolve_user_in_all_required_nodes(wfs):
    for wid, names in REQUIRED_RESOLVE_USER.items():
        for name in names:
            code = node(wfs[wid], name)["parameters"]["jsCode"]
            assert "function resolveUser" in code, f"{wid}/{name}: нет resolveUser"
            assert code.count("resolveUser(") >= 1, f"{wid}/{name}: resolveUser не вызван"


def test_all_connections_point_to_existing_nodes(wfs):
    for wid, wf in wfs.items():
        names = {n["name"] for n in wf["nodes"]}
        for src, conn in wf["connections"].items():
            assert src in names, f"{wid}: источник {src} не найден"
            for branch in conn.get("main") or []:
                for target in branch or []:
                    assert target["node"] in names, f"{wid}: {src}→{target['node']} в никуда"


def test_no_secrets_in_workflow_files(wfs):
    blob = json.dumps(wfs, ensure_ascii=False)
    for marker in ("AAH", "cd8b30b650f89cebc61e88"):
        assert marker not in blob, f"в JSON просочился секрет ({marker})"
    assert "__BOT_TOKEN__" in blob and "__SIGN_SECRET__" in blob


def test_wizard_step_text_uses_escaped_newlines(wfs):
    """Регрессия: в JS-строку текста шага попал реальный перевод строки (синтаксическая ошибка)."""
    code = node(wfs["demo-11"], "Маршрут wizard")["parameters"]["jsCode"]
    esc = chr(92)
    assert f"проверьте:{esc}n" in code, "перенос в тексте шага должен быть \n-экраном, а не сырым переводом"
