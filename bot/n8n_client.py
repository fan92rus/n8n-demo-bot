"""HTTP-клиент к n8n-воркфлоу демо-стенда (CT100).

Все вызовы идут по локальной сети на вебхуки n8n:
  POST /webhook/demo/classify {"text": ...}   -> {"ok":true,"category":...,"priority":...,"summary":...}
  POST /webhook/demo/slots    {}              -> {"ok":true,"slots":[{"id":...,"label":...,"start":...}]}
  POST /webhook/demo/book     {"slot_id","user"} -> {"ok":true,"booking":{...}}
"""

from __future__ import annotations

import httpx


class N8nError(RuntimeError):
    """Сервис n8n недоступен или вернул ошибку."""


class N8nClient:
    def __init__(
        self,
        base_url: str,
        timeout: float = 90.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout
        self._transport = transport

    async def classify(self, text: str) -> dict:
        return await self._post("/webhook/demo/classify", {"text": text})

    async def slots(self) -> list[dict]:
        data = await self._post("/webhook/demo/slots", {})
        slots = data.get("slots", []) if isinstance(data, dict) else data
        if not isinstance(slots, list):
            raise N8nError("n8n вернул slots не списком")
        return slots

    async def book(self, slot_id: str, user: str) -> dict:
        return await self._post("/webhook/demo/book", {"slot_id": slot_id, "user": user})

    async def _post(self, path: str, payload: dict) -> dict:
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                resp = await client.post(f"{self._base}{path}", json=payload)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPError as e:
            raise N8nError(f"n8n {path}: {e}") from e
        except ValueError as e:
            raise N8nError(f"n8n {path}: ответ не JSON ({e})") from e
