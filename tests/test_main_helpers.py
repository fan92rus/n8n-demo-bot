"""Тесты хелперов main.py (импортируем main целиком — aiogram установлен)."""

from __future__ import annotations

from bot.main import (
    PENDING_CLARIFY,
    cb_bytes_fit,
    kb_from_buttons,
    pending_get,
    pending_pop,
    pending_put,
)


def test_cb_bytes_fit_limits_to_64_bytes():
    s = "wz:" + "ф" * 100  # кириллица = 2 байта/символ
    out = cb_bytes_fit(s)
    assert len(out.encode("utf-8")) <= 64


def test_kb_from_buttons_skips_garbage():
    rows = [
        [{"text": "ок", "callback_data": "wz:srv:consult"}],
        ["строка вместо dict", {"callback_data": "нет-текста"}, {"text": "нет-cb"}, None],
        {"вообще": "не список"},
    ]
    kb = kb_from_buttons(rows)
    assert kb is not None
    assert len(kb.inline_keyboard) == 1
    assert kb.inline_keyboard[0][0].callback_data == "wz:srv:consult"


def test_kb_from_buttons_garbage_only_returns_none():
    assert kb_from_buttons([[None, 1, "x"]]) is None
    assert kb_from_buttons(None) is None
    assert kb_from_buttons("мусор") is None


def test_pending_ttl_and_pop():
    pending_put(111, 7, "нужен бот")
    assert pending_get(111, 7) == "нужен бот"
    PENDING_CLARIFY[(222, 8)] = ("старое", 0.0)  # протухшая запись (monotonic=0 — давно)
    assert pending_get(222, 8) is None
    assert pending_pop(333, 9) is None
    assert pending_pop(111, 7) == "нужен бот"
    assert pending_get(111, 7) is None


def test_pending_keys_are_per_user():
    """M6: в одном чате у разных пользователей уточнения не смешиваются."""
    pending_put(555, 1, "бот для сайта")
    pending_put(555, 2, "CRM-интеграция")
    assert pending_get(555, 1) == "бот для сайта"
    assert pending_get(555, 2) == "CRM-интеграция"
    assert pending_pop(555, 1) == "бот для сайта"
    assert pending_get(555, 1) is None
    assert pending_get(555, 2) == "CRM-интеграция"
