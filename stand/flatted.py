"""Мини-декодер flatted-формата n8n (как flatted@3 parse, см. cjs/index.js).

n8n хранит execution_data.data в sqlite в виде flatted-JSON: корневой объект в
arr[0], все остальные значения — в массиве; ссылки — строки-индексы. Строковые
данные тоже лежат в массиве и подставляются по индексу. Массивы разворачиваются
как объекты с числовыми ключами (в JS Object.keys у массивов — индексы). Циклы
разматываются «лениво» (lazy), как в оригинале.
"""

from __future__ import annotations

import json
from typing import Any

_IGNORE = object()


def _items(obj: Any):
    if isinstance(obj, dict):
        return list(obj.items())
    if isinstance(obj, list):
        return list(enumerate(obj))
    return []


def decode(arr: list[Any]) -> Any:
    """Развернуть flatted-массив в обычный объект (циклические ссылки сохраняются)."""
    value = arr[0]
    if not (isinstance(value, dict) or isinstance(value, list)):
        return value
    lazy: list[tuple[Any, Any, Any]] = []
    seen: set[int] = set()

    def resolve(obj: Any) -> None:
        for k, v in _items(obj):
            if isinstance(v, str) and v.isdigit():
                idx = int(v)
                tmp = arr[idx] if 0 <= idx < len(arr) else None
                if isinstance(tmp, (dict, list)):
                    if id(tmp) not in seen:
                        seen.add(id(tmp))
                        obj[k] = _IGNORE
                        lazy.append((obj, k, tmp))
                    else:
                        obj[k] = tmp  # общий объект уже разворачивается в lazy-цикле
                else:
                    obj[k] = tmp
        return None

    resolve(value)
    i = 0
    while i < len(lazy):
        o, k, r = lazy[i]
        i += 1
        resolve(r)
        o[k] = r
    return value


def loads(text: str) -> Any:
    """flatted_loads: JSON-строка execution_data -> развёрнутый объект."""
    return decode(json.loads(text))
