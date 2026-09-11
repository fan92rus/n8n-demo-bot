"""Форматирование ответов n8n для человека (чистые функции, легко тестируются)."""

from __future__ import annotations


def format_classify(r: dict) -> str:
    cat = r.get("category", "?")
    prio = r.get("priority", "?")
    summary = (r.get("summary") or "").strip()[:800]  # лимит Telegram на сообщение (4096)
    lines = [f"Категория: {cat}", f"Приоритет: {prio}"]
    if summary:
        lines.append(f"Суть: {summary}")
    return "\n".join(lines)


def format_slots(slots: list[dict]) -> str:
    if not slots:
        return "Свободных слотов нет — всё разобрано."
    lines = ["Свободные слоты:"]
    for s in slots:
        if not isinstance(s, dict):
            continue
        lines.append(f"• {s.get('label') or s.get('id') or '?'} — {s.get('start') or ''}")
    lines.append("")
    lines.append("Нажмите на слот ниже, чтобы записаться")
    return "\n".join(lines)


def format_booking(booking: dict) -> str:
    if booking.get("ok") is False:
        return f"Не получилось: {booking.get('error', 'слот занят или не найден')}"
    slot = booking.get("booking") or booking  # {"ok":true,"booking":null} — не None
    if not isinstance(slot, dict):
        return "Записал. Подтверждение — в «Мои записи»."
    return (
        f"Записал: {slot.get('label') or slot.get('slot_id') or '?'} — "
        f"{slot.get('start') or ''}. Ждём вас!"
    )
