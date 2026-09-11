"""Тесты форматтеров ответов."""

from __future__ import annotations

from bot.format import format_booking, format_classify, format_slots


def test_format_classify_full():
    s = format_classify(
        {"category": "бот", "priority": "высокий", "summary": "Телеграм-бот"}
    )
    assert "бот" in s and "высокий" in s and "Телеграм-бот" in s


def test_format_classify_missing_fields():
    s = format_classify({})
    assert "?" in s


def test_format_slots_empty():
    assert "нет" in format_slots([])


def test_format_slots_list():
    s = format_slots([{"id": "s1", "label": "Пн 10:00", "start": "10:00"}])
    assert "Пн 10:00" in s and "/book" in s


def test_format_booking_ok():
    s = format_booking({"ok": True, "booking": {"label": "Пн 10:00", "start": "10:00"}})
    assert "Записал" in s


def test_format_booking_failure():
    s = format_booking({"ok": False, "error": "занят"})
    assert "Не получилось" in s


def test_format_leads_empty():
    from bot.format import format_leads

    assert "Лидов пока нет" in format_leads([])


def test_format_leads_list():
    from bot.format import format_leads

    out = format_leads([{"user": "@t", "category": "интеграция", "priority": "высокий", "summary": "CRM"}])
    assert "интеграция" in out and "@t" in out
