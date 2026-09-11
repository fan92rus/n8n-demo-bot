"""Identity-патч воркфлоу (батч 3): пользователь доверяется только по подписи.

Два доверенных пути:
1) бот шлёт {user, sig}, где sig = HMAC-SHA256(DEMO_SIGN_SECRET, user);
2) мини-апп шлёт {init_data} — Telegram initData, hash проверяется по bot_token.

Всё остальное (голый body.user) трактуется как аноним/отказ.

Секреты НЕ хранятся в JSON (репо публичный): в файлах плейсхолдеры
__BOT_TOKEN__ / __SIGN_SECRET__, при деплое подставляются из окружения CT100.

Режимы:
  python patch_identity.py            — патч локальных stand/*.json (плейсхолдеры остаются)
  python patch_identity.py --deploy   — подставить секреты из /root/n8n-demo-bot.env,
                                        залить в sqlite (entity + все history) demo-09/10/11
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
FILES = {
    "demo-09": "demo-09-ai-classifier.json",
    "demo-10": "demo-10-booking.json",
    "demo-11": "demo-11-wizard.json",
}

RESOLVE_JS = """function resolveUser(body) {
  const crypto = require('crypto');
  try {
    if (body.init_data) {
      // ручной разбор строки initData (без стандартного URL-парсера:
      // в песочнице Code node он недоступен);
      // data_check_string строится из СЫРЫХ значений, как требует Telegram
      const raw = String(body.init_data);
      let hash = '';
      const pairs = [];
      for (const part of raw.split('&')) {
        const eq = part.indexOf('=');
        if (eq < 0) continue;
        const k = part.slice(0, eq);
        const v = part.slice(eq + 1);
        if (k === 'hash') { hash = v; continue; }
        if (k === 'signature') continue;
        pairs.push([k, v]);
      }
      const dcs = pairs.map(([k, v]) => k + '=' + v).sort().join('&');
      const secret = crypto.createHmac('sha256', 'WebAppData').update('__BOT_TOKEN__').digest();
      const calc = crypto.createHmac('sha256', secret).update(dcs).digest('hex');
      if (!hash || calc !== hash) return null;
      const uv = (pairs.find(([k]) => k === 'user') || [])[1] || '{}';
      const u = JSON.parse(decodeURIComponent(uv));
      return u.username ? '@' + String(u.username) : (u.id ? String(u.id) : null);
    }
    if (body.user && body.sig) {
      const calc = crypto.createHmac('sha256', '__SIGN_SECRET__').update(String(body.user)).digest('hex');
      return calc === String(body.sig) ? String(body.user) : null;
    }
  } catch (e) {
    return null;
  }
  return null;
}
"""

# ноды, в начало jsCode которых добавляется resolveUser
INJECT = {
    "demo-09": ["Валидация", "Лиды", "Присвоить дату"],
    "demo-10": ["Бронь", "Мои записи", "Отмена"],
    "demo-11": ["Маршрут wizard"],
}

# точечные замены (wid, node, old, new)
EDITS = [
    ("demo-09", "Валидация",
     "return [{ json: { text, user: String(body.user || 'аноним').slice(0, 64) } }];",
     "const uid = resolveUser(body);\nreturn [{ json: { text, user: uid ? uid.slice(0, 64) : null } }];"),
    ("demo-09", "Лид-захват",
     "const src = $('Валидация').first().json;",
     "const src = $('Валидация').first().json;\nif (!src.user) { return [{ json: { ...$json, lead_saved: false } }]; }"),
    ("demo-09", "Лиды",
     "const user = (($('Webhook leads').first().json.body) || {}).user || '';",
     "const user = resolveUser(($('Webhook leads').first().json.body) || {}) || '';"),
    ("demo-09", "Присвоить дату",
     "const user = String(body.user || '');",
     "const user = resolveUser(body) || '';"),
    ("demo-10", "Бронь",
     "const user = String(body.user || 'unknown').slice(0, 64);",
     "const user = (resolveUser(body) || '').slice(0, 64);\nif (!user) { return [{ json: { ok: false, error: 'unauthorized' } }]; }"),
    ("demo-10", "Мои записи",
     "const user = String(body.user || '');",
     "const user = resolveUser(body) || '';\nif (!user) { return [{ json: { ok: true, bookings: [] } }]; }"),
    ("demo-10", "Отмена",
     "const user = String(body.user || '');",
     "const user = resolveUser(body) || '';"),
    ("demo-11", "Маршрут wizard",
     "const u = String(body.user || '').trim().slice(0, 64);\n  out = { stage: 'book', slot_id: slotId, user: u || ('wizard-demo (' + (services[svc] || svc) + ')') };",
     "const u = (resolveUser(body) || '').trim().slice(0, 64);\n  if (!u) {\n    out = { stage: 'show', text: '⚠️ Не удалось подтвердить личность. Откройте демо через бота.', buttons: kb([[['🔄 С начала', 'wz:start']]]) };\n  } else {\n    out = { stage: 'book', slot_id: slotId, user: u };\n  }"),
]


def patch_workflow(wid: str, wf: dict) -> None:
    nodes = {n["name"]: n for n in wf["nodes"]}
    for name in INJECT[wid]:
        code = nodes[name]["parameters"]["jsCode"]
        if "function resolveUser" in code:
            code = code[code.index("function resolveUser"):]
            code = code[code.index("}\n") + 2:] if "}\n" in code[: len(RESOLVE_JS) + 50] else code
        assert "function resolveUser" not in code, f"{wid}/{name}: resolveUser уже есть"
        nodes[name]["parameters"]["jsCode"] = RESOLVE_JS + code
    for w, name, old, new in EDITS:
        if w != wid:
            continue
        code = nodes[name]["parameters"]["jsCode"]
        assert old in code, f"{wid}/{name}: якорь не найден: {old[:60]!r}"
        code = code.replace(old, new, 1)
        nodes[name]["parameters"]["jsCode"] = code
    for name in INJECT[wid]:
        code = nodes[name]["parameters"]["jsCode"]
        assert code.count("resolveUser(") >= 2 or name in ("Бронь",), f"{wid}/{name}: resolveUser не вызван"
    # самопроверка: новая строка присутствует, а для полных замен старая — отсутствует
    for w, name, old, new in EDITS:
        if w != wid:
            continue
        code = nodes[name]["parameters"]["jsCode"]
        assert new.split("\n")[0] in code, f"{wid}/{name}: новый код не встал"
        if old not in new:
            assert old not in code, f"{wid}/{name}: старый код остался"


def load_env_secrets() -> dict:
    env = {}
    for line in Path("/root/n8n-demo-bot.env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    assert env.get("BOT_TOKEN"), "BOT_TOKEN не найден в /root/n8n-demo-bot.env"
    assert env.get("DEMO_SIGN_SECRET"), "DEMO_SIGN_SECRET не найден в /root/n8n-demo-bot.env"
    return {"__BOT_TOKEN__": env["BOT_TOKEN"], "__SIGN_SECRET__": env["DEMO_SIGN_SECRET"]}


def push_db(wfs: dict[str, dict], secrets: dict[str, str]) -> None:
    """Заливка в БД ПРАВИЛЬНО: колонка nodes = json.dumps(wf['nodes']) (только массив)."""
    con = sqlite3.connect("/root/n8n/data/database.sqlite")
    for wid, wf in wfs.items():
        nodes_json = json.dumps(wf["nodes"], ensure_ascii=False)
        conns_json = json.dumps(wf["connections"], ensure_ascii=False)
        nodes_json = nodes_json.replace("__BOT_TOKEN__", secrets["__BOT_TOKEN__"]).replace(
            "__SIGN_SECRET__", secrets["__SIGN_SECRET__"]
        )
        conns_json = conns_json.replace("__BOT_TOKEN__", secrets["__BOT_TOKEN__"]).replace(
            "__SIGN_SECRET__", secrets["__SIGN_SECRET__"]
        )
        assert isinstance(json.loads(nodes_json), list), f"{wid}: nodes не массив"
        con.execute(
            "update workflow_entity set nodes=?, connections=?, active=1, activeVersionId=versionId where id=?",
            (nodes_json, conns_json, wid),
        )
        con.execute(
            "update workflow_history set nodes=?, connections=? where workflowId=?",
            (nodes_json, conns_json, wid),
        )
        print(f"{wid}: залито в БД (nodes=массив)")
    con.commit()
    con.close()


def main() -> int:
    deploy = "--deploy" in sys.argv or "--push-db" in sys.argv
    secrets = load_env_secrets() if deploy else {}
    wfs: dict[str, dict] = {}
    for wid, fname in FILES.items():
        wf = json.loads((BASE / fname).read_text(encoding="utf-8"))
        if "--push-db" in sys.argv:
            # файлы уже пропатчены локально — только заливка
            assert "function resolveUser" in wf["nodes"][0]["parameters"].get("jsCode", "") or any(
                "function resolveUser" in (n.get("parameters") or {}).get("jsCode", "") for n in wf["nodes"]
            ), f"{wid}: в файле нет resolveUser — сначала патч"
        else:
            patch_workflow(wid, wf)
        wfs[wid] = wf
        out = json.dumps(wf, ensure_ascii=False)
        if deploy:
            out = out.replace("__BOT_TOKEN__", secrets["__BOT_TOKEN__"]).replace(
                "__SIGN_SECRET__", secrets["__SIGN_SECRET__"]
            )
        if "--push-db" in sys.argv:
            pass  # заливка ниже, отдельным корректным способом
        elif deploy:
            raise SystemExit("--deploy больше не пишет в БД; используй --push-db после scp файлов")
        else:
            (BASE / fname).write_text(out, encoding="utf-8")
            assert "__BOT_TOKEN__" in out and "__SIGN_SECRET__" in out
            print(f"{wid}: локально пропатчен (плейсхолдеры на месте)")
    if "--push-db" in sys.argv:
        push_db(wfs, secrets)
    if not deploy:
        # контроль: секретов в файлах нет
        for wid, fname in FILES.items():
            raw = (BASE / fname).read_text(encoding="utf-8")
            for marker in ("AAH", "cd8b30b650f89cebc61e88"):
                assert marker not in raw, f"{wid}: похоже, просочился секрет"
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
