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
    assert "Пн 10:00" in s and "/book" not in s



def test_format_booking_null_booking():
    # контракт {"ok":true,"booking":null} не должен ронять форматтер
    assert "Записал" in format_booking({"ok": True, "booking": None})


def test_format_slots_none_labels():
    slots = [{"id": "s1", "label": None, "start": "2026-09-14T10:00"}, {"id": "s2", "label": "день"}]
    out = format_slots(slots)
    assert "None" not in out
    assert "s1" in out and "день" in out


def test_format_classify_long_summary_capped():
    out = format_classify({"category": "бот", "priority": "высокий", "summary": "х" * 5000})
    assert len(out) < 2000


def test_format_slots_skips_garbage_items():
    out = format_slots([None, "мусор", 42, {"id": "s1", "label": "день", "start": "14:00"}])
    assert "None" not in out and "день" in out


def test_format_booking_non_dict_booking():
    # {"ok":true,"booking":123} — booking не dict: короткое подтверждение без падения
    assert "Записал" in format_booking({"ok": True, "booking": 123})
