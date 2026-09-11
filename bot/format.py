"""Форматирование ответов n8n для человека (чистые функции, легко тестируются)."""

from __future__ import annotations


def format_classify(r: dict) -> str:
    cat = r.get("category", "?")
    prio = r.get("priority", "?")
    summary = (r.get("summary") or "").strip()
    lines = [f"Категория: {cat}", f"Приоритет: {prio}"]
    if summary:
        lines.append(f"Суть: {summary}")
    return "\n".join(lines)


def format_slots(slots: list[dict]) -> str:
    if not slots:
        return "Свободных слотов нет — всё разобрано."
    lines = ["Свободные слоты:"]
    for s in slots:
        lines.append(f"• {s.get('label', s.get('id', '?'))} — {s.get('start', '')}")
    lines.append("")
    lines.append("Нажмите на слот ниже, чтобы записаться")
    return "\n".join(lines)


def format_booking(booking: dict) -> str:
    if booking.get("ok") is False:
        return f"Не получилось: {booking.get('error', 'слот занят или не найден')}"
    slot = booking.get("booking", booking)
    return (
        f"Записал: {slot.get('label', slot.get('slot_id', '?'))} — "
        f"{slot.get('start', '')}. Ждём вас!"
    )


def format_leads(leads: list[dict], private: bool = True) -> str:
    """Лиды. private=True — каждый видит только свои (галка leads_private в n8n)."""
    if not leads:
        return "Своих заявок пока нет. Пришли боту текст заявки — она попадёт в очередь."
    header = "📋 Ваши заявки (приватно — чужие скрыты):" if private else "📋 Все заявки (режим менеджера):"
    lines = [header]
    for lead in leads[:15]:
        lines.append(
            f"• {lead.get('category', '?')} / {lead.get('priority', '?')} — "
            f"{(lead.get('summary') or '')[:60]} ({lead.get('user', '?')})"
        )
    if len(leads) > 15:
        lines.append(f"…и ещё {len(leads) - 15}")
    return "\n".join(lines)
