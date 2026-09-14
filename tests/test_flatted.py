"""Тест мини-декодера flatted (n8n execution_data).

Фикстура flatted_sample.json сгенерирована настоящей библиотекой flatted@3
(та, что в контейнере n8n), поэтому декодер проверяется против реального кодировщика.
"""

from __future__ import annotations

import json
from pathlib import Path

from stand.flatted import decode, loads

FIX = Path(__file__).resolve().parent / "fixtures" / "flatted_sample.json"


def _find_json(obj):
    """Достать первый словарь с ключом json из произвольной структуры flatted-фикстуры."""
    if isinstance(obj, dict):
        if "json" in obj:
            return obj["json"]
        for v in obj.values():
            hit = _find_json(v)
            if hit is not None:
                return hit
    elif isinstance(obj, list):
        for v in obj:
            hit = _find_json(v)
            if hit is not None:
                return hit
    return None


def test_decode_real_flatted_fixture():
    obj = loads(FIX.read_text(encoding="utf-8"))
    assert obj["version"] == 1
    run = obj["resultData"]["runData"]["Слоты"][0]
    payload = _find_json(run["data"]["main"])
    assert payload is not None and payload["ok"] is True
    assert payload["slots"][0]["id"] == "2026-09-16-1000"
    assert obj["nested"]["list"] == [1, 2, {"deep": "text"}]
    assert obj["shared"] is obj["nested"]  # общая ссылка сохраняется (не дублируется)


def test_decode_string_data_and_shared_object():
    obj = decode(json.loads('[{"a":"1","b":"1"},{"x":"2"},5]'))
    assert obj["a"] is obj["b"]
    assert obj["a"] == {"x": 5}


def test_decode_cycle_is_preserved():
    obj = decode(json.loads('[{"self":"0"}]'))
    assert obj["self"] is obj


def test_decode_scalar_root():
    assert decode(["hello"]) == "hello"
