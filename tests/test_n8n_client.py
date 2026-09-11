"""Тесты n8n-клиента на httpx.MockTransport (без сети и без aiogram)."""

from __future__ import annotations

import httpx
import pytest

from bot.n8n_client import N8nClient, N8nError


def make_client(handler) -> N8nClient:
    return N8nClient("http://n8n.test", transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_classify_ok():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/webhook/demo/classify"
        import json

        body = json.loads(request.content)
        assert body["text"] == "нужен CRM"
        return httpx.Response(
            200,
            json={"ok": True, "category": "интеграция", "priority": "средний", "summary": "CRM"},
        )

    r = await make_client(handler).classify("нужен CRM")
    assert r["ok"] is True
    assert r["category"] == "интеграция"


@pytest.mark.asyncio
async def test_classify_http_error_raises_n8n_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"message": "Error in workflow"})

    with pytest.raises(N8nError):
        await make_client(handler).classify("тест")


@pytest.mark.asyncio
async def test_classify_non_json_raises_n8n_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>oops</html>")

    with pytest.raises(N8nError):
        await make_client(handler).classify("тест")


@pytest.mark.asyncio
async def test_slots_dict_payload():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "ok": True,
                "slots": [{"id": "s1", "label": "Пн 10:00", "start": "2026-09-15T10:00"}],
            },
        )

    slots = await make_client(handler).slots()
    assert slots[0]["id"] == "s1"


@pytest.mark.asyncio
async def test_slots_bad_payload_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"slots": "not-a-list"})

    with pytest.raises(N8nError):
        await make_client(handler).slots()


@pytest.mark.asyncio
async def test_book_sends_slot_and_user():
    import json

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body == {"slot_id": "s2", "user": "@tester"}
        return httpx.Response(200, json={"ok": True, "booking": {"slot_id": "s2"}})

    r = await make_client(handler).book("s2", "@tester")
    assert r["ok"] is True


@pytest.mark.asyncio
async def test_wizard_step_passthrough():
    """wizard() передаёт sel в n8n и возвращает текст+кнопки как есть."""
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/webhook/demo/wizard"
        import json

        body = json.loads(request.content)
        assert body["sel"] == "srv:consult"
        return httpx.Response(
            200,
            json={
                "text": "Шаг 2/3: выберите время",
                "buttons": [[{"text": "📅 слот", "callback_data": "wz:time:2026-09-14-1000:consult"}]],
            },
        )

    r = await make_client(handler).wizard("srv:consult")
    assert r["text"].startswith("Шаг 2/3")
    assert r["buttons"][0][0]["callback_data"].startswith("wz:time:")
