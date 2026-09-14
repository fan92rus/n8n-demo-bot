"""HTTP-клиент к n8n-воркфлоу демо-стенда (CT100).

Все вызовы идут по локальной сети на вебхуки n8n:
  POST /webhook/demo/classify {"text": ...}   -> {"ok":true,"category":...,"priority":...,"summary":...}
  POST /webhook/demo/slots    {}              -> {"ok":true,"slots":[{"id":...,"label":...,"start":...}]}
  POST /webhook/demo/book     {"slot_id","user"} -> {"ok":true,"booking":{...}}
  POST /webhook/demo/wizard   {"sel": ...}    -> {"text":...,"buttons":[[{"text","callback_data"}]]}
  POST /webhook/demo/my       {"user"}        -> {"ok":true,"bookings":[{"slot_id","start","user"}]}
  POST /webhook/demo/cancel   {"slot_id","user"} -> {"ok":true,"freed":...} | {"ok":false,"error":...}
  POST /webhook/demo/leads    {}              -> {"ok":true,"leads":[{"user","text","category",...}]}
  POST /webhook/demo/lead_date {"user","date"} -> {"ok":true} — дата на последнюю открытую заявку
"""

from __future__ import annotations

import hashlib
import hmac

import httpx


class N8nError(RuntimeError):
    """Сервис n8n недоступен или вернул ошибку."""


class N8nClient:
    def __init__(
        self,
        base_url: str,
        timeout: float = 90.0,
        transport: httpx.AsyncBaseTransport | None = None,
        sign_secret: str = "",
    ) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout
        self._transport = transport
        self._sign_secret = sign_secret

    @staticmethod
    def sign_user(secret: str, user: str) -> str:
        """HMAC-SHA256(user) — воркфлоу n8n доверяет user только с этой подписью."""
        return hmac.new(secret.encode(), str(user).encode(), hashlib.sha256).hexdigest()

    async def classify(self, text: str, user: str | None = None) -> dict:
        payload: dict = {"text": text}
        if user:
            payload["user"] = user
        return await self._post("/webhook/demo/classify", payload)

    async def slots(self) -> list[dict]:
        data = await self._post("/webhook/demo/slots", {})
        raw = data.get("slots", []) if isinstance(data, dict) else data
        if not isinstance(raw, list):
            raise N8nError("n8n вернул slots не списком")
        slots: list[dict] = []
        for s in raw:
            if isinstance(s, dict) and isinstance(s.get("id"), str) and s["id"]:
                slots.append(s)
        return slots

    async def book(self, slot_id: str, user: str) -> dict:
        return await self._post("/webhook/demo/book", {"slot_id": slot_id, "user": user})

    async def lead_date(self, user: str, date: str, lead_id: str | None = None) -> dict:
        """Проставить дату консультации в конкретную заявку.

        lead_id — заявка, которую оформляли (M5: не писать дату в «последнюю»);
        без lead_id воркфлоу использует последнюю открытую заявку пользователя.
        """
        payload: dict = {"user": user, "date": date}
        if lead_id:
            payload["lead_id"] = lead_id
        return await self._post("/webhook/demo/lead_date", payload)

    async def wizard(self, sel: str, user: str | None = None) -> dict:
        """Один шаг wizard'а: sel='start' или состояние из callback_data (текст после 'wz:').

        Бот stateless — всё состояние шага передаётся в кнопках; n8n возвращает
        текст и новую раскладку кнопок (кнопки меняются по шагам).
        user — реальный пользователь: на финале визарда бронь пишется на него.
        """
        payload: dict = {"sel": sel}
        if user:
            payload["user"] = user
        return await self._post("/webhook/demo/wizard", payload)

    async def my_bookings(self, user: str) -> dict:
        """Список броней пользователя (демо-стенд хранит их в staticData)."""
        return await self._post("/webhook/demo/my", {"user": user})

    async def cancel_booking(self, slot_id: str, user: str) -> dict:
        """Отмена своей брони — слот снова попадает в /slots."""
        return await self._post("/webhook/demo/cancel", {"slot_id": slot_id, "user": user})

    async def _post(self, path: str, payload: dict) -> dict:
        if self._sign_secret and payload.get("user"):
            payload = dict(payload)
            payload["sig"] = self.sign_user(self._sign_secret, payload["user"])
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                resp = await client.post(f"{self._base}{path}", json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as e:
            raise N8nError(f"n8n {path}: {e}") from e
        except ValueError as e:
            raise N8nError(f"n8n {path}: ответ не JSON ({e})") from e
        if not isinstance(data, dict):
            raise N8nError(f"n8n {path}: ответ не объект ({type(data).__name__})")
        return data
