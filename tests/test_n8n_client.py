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


@pytest.mark.asyncio
async def test_classify_passes_user():
    def handler(request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content)
        assert body["text"] == "нужен бот"
        assert body["user"] == "@tester"
        return httpx.Response(200, json={"ok": True, "category": "бот"})

    r = await make_client(handler).classify("нужен бот", "@tester")
    assert r["ok"] is True


@pytest.mark.asyncio
async def test_my_bookings():
    def handler(request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content)
        assert body["user"] == "@tester"
        return httpx.Response(
            200,
            json={"ok": True, "bookings": [{"slot_id": "2026-09-14-1000", "start": "2026-09-14 10:00", "user": "@tester"}]},
        )

    r = await make_client(handler).my_bookings("@tester")
    assert r["bookings"][0]["slot_id"] == "2026-09-14-1000"


@pytest.mark.asyncio
async def test_cancel_booking():
    def handler(request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content)
        assert body["slot_id"] == "2026-09-14-1000"
        assert body["user"] == "@tester"
        return httpx.Response(200, json={"ok": True, "freed": "2026-09-14 10:00"})

    r = await make_client(handler).cancel_booking("2026-09-14-1000", "@tester")
    assert r["ok"] is True
    assert "freed" in r



@pytest.mark.asyncio
async def test_post_rejects_non_dict():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[1, 2, 3])

    with pytest.raises(N8nError):
        await make_client(handler).classify("тест")


@pytest.mark.asyncio
async def test_slots_filters_bad_items():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"slots": [{"id": "2026-09-14-1000", "label": "утро"}, 42, "x", {"label": "нет id"}, None]},
        )

    slots = await make_client(handler).slots()
    assert len(slots) == 1
    assert slots[0]["id"] == "2026-09-14-1000"


@pytest.mark.asyncio
async def test_signing_adds_sig_hmac():
    """Бот подписывает user, когда задан sign_secret (identity-контракт)."""

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content)
        assert body["user"] == "@tester"
        expected = N8nClient.sign_user("sekret", "@tester")
        assert body["sig"] == expected
        return httpx.Response(200, json={"ok": True})

    client = N8nClient("http://n8n.test", transport=httpx.MockTransport(handler), sign_secret="sekret")
    r = await client.book("s1", "@tester")
    assert r["ok"] is True


def test_sign_user_is_stable_hmac_sha256():
    a = N8nClient.sign_user("sekret", "@tester")
    b = N8nClient.sign_user("sekret", "@tester")
    c = N8nClient.sign_user("sekret", "@other")
    assert a == b and a != c
    assert len(a) == 64


@pytest.mark.asyncio
async def test_lead_date_passes_lead_id():
    import json

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body == {"user": "@tester", "date": "2026-09-21 10:00", "lead_id": "L42"}
        return httpx.Response(200, json={"ok": True})

    r = await make_client(handler).lead_date("@tester", "2026-09-21 10:00", lead_id="L42")
    assert r["ok"] is True


@pytest.mark.asyncio
async def test_lead_date_without_lead_id_fallback():
    import json

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert "lead_id" not in body
        return httpx.Response(200, json={"ok": True})

    r = await make_client(handler).lead_date("@tester", "2026-09-21 10:00")
    assert r["ok"] is True


@pytest.mark.asyncio
async def test_non_dict_response_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=["not", "an", "object"])

    with pytest.raises(N8nError):
        await make_client(handler).wizard("start")


@pytest.mark.asyncio
async def test_my_cancel_methods():
    import json

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        body = json.loads(request.content)
        if request.url.path == "/webhook/demo/my":
            assert body == {"user": "@tester"}
            return httpx.Response(200, json={"ok": True, "bookings": []})
        assert body == {"slot_id": "s1", "user": "@tester"}
        return httpx.Response(200, json={"ok": True, "freed": "2026-09-16 10:00"})

    c = make_client(handler)
    assert (await c.my_bookings("@tester"))["ok"] is True
    r = await c.cancel_booking("s1", "@tester")
    assert r["freed"].startswith("2026-09-16")
