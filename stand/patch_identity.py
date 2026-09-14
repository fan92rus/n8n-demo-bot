"""Identity-патч воркфлоу: пользователь доверяется только по подписи.

Два доверенных пути:
1) бот шлёт {user, sig}, где sig = HMAC-SHA256(DEMO_SIGN_SECRET, user);
2) мини-апп шлёт {init_data} — Telegram initData, hash проверяется по bot_token.

Всё остальное (голый body.user) трактуется как аноним/отказ.

Секреты НЕ хранятся в JSON (репо публичный): в файлах плейсхолдеры
__BOT_TOKEN__ / __SIGN_SECRET__, при деплое подставляются из окружения CT100.

Режимы:
  python patch_identity.py            — патч локальных stand/*.json (идемпотентно)
  python patch_identity.py --push-db  — заливка в sqlite (entity + history по activeVersionId)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
if str(BASE.parent) not in sys.path:
    sys.path.insert(0, str(BASE.parent))

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

# ноды, в начало jsCode которых добавляется resolveUser (инъекция, если его нет)
INJECT = {
    "demo-09": ["Валидация", "Лиды", "Присвоить дату"],
    "demo-10": ["Бронь", "Мои записи", "Отмена"],
    "demo-11": ["Маршрут wizard"],
}

# точечные замены: (wid, node, старый код, новый код, маркер «уже применено»)
EDITS = [
    ("demo-09", "Валидация",
     "return [{ json: { text, user: String(body.user || 'аноним').slice(0, 64) } }];",
     "const uid = resolveUser(body);\n"
     "if (!uid) {\n"
     "  return [{ json: { ok: false, error: 'unauthorized: подпись пользователя не подтверждена' } }];\n"
     "}\n"
     "return [{ json: { text, user: uid.slice(0, 64) } }];",
     "unauthorized: подпись пользователя не подтверждена"),
    ("demo-09", "Лид-захват",
     "const src = $('Валидация').first().json;",
     "const src = $('Валидация').first().json;\nif (!src.user) { return [{ json: { ...$json, lead_saved: false } }]; }",
     "if (!src.user)"),
    ("demo-09", "Лиды",
     "const user = (($('Webhook leads').first().json.body) || {}).user || '';",
     "const user = resolveUser(($('Webhook leads').first().json.body) || {}) || '';",
     "resolveUser(("),
    ("demo-09", "Присвоить дату",
     "const user = String(body.user || '');",
     "const user = resolveUser(body) || '';",
     "resolveUser(body)"),
    ("demo-10", "Бронь",
     "const user = String(body.user || 'unknown').slice(0, 64);",
     "const user = (resolveUser(body) || '').slice(0, 64);\nif (!user) { return [{ json: { ok: false, error: 'unauthorized' } }]; }",
     "unauthorized"),
    ("demo-10", "Мои записи",
     "const user = String(body.user || '');",
     "const user = resolveUser(body) || '';\nif (!user) { return [{ json: { ok: true, bookings: [] } }]; }",
     "resolveUser(body)"),
    ("demo-10", "Отмена",
     "const user = String(body.user || '');",
     "const user = resolveUser(body) || '';",
     "resolveUser(body)"),
    ("demo-11", "Маршрут wizard",
     "const u = String(body.user || '').trim().slice(0, 64);\n"
     "  out = { stage: 'book', slot_id: slotId, user: u || ('wizard-demo (' + (services[svc] || svc) + ')') };",
     "const u = (resolveUser(body) || '').trim().slice(0, 64);\n"
     "  if (!u) {\n"
     "    out = { stage: 'show', text: '⚠️ Не удалось подтвердить личность. Откройте демо через бота.', buttons: kb([[['🔄 С начала', 'wz:start']]]) };\n"
     "  } else {\n"
     "    out = { stage: 'book', slot_id: slotId, user: u };\n"
     "  }",
     "Не удалось подтвердить личность"),
]


def has_resolve_user_definition(code: str) -> bool:
    return "function resolveUser" in code


def patch_workflow(wid: str, wf: dict) -> list[str]:
    """Идемпотентно наложить identity-патч; вернуть список изменений."""
    nodes = {n["name"]: n for n in wf["nodes"]}
    changed: list[str] = []
    for name in INJECT[wid]:
        code = nodes[name]["parameters"]["jsCode"]
        if has_resolve_user_definition(code):
            continue  # уже есть — не трогаем (повторный запуск безопасен)
        nodes[name]["parameters"]["jsCode"] = RESOLVE_JS + code
        changed.append(f"inject resolveUser:{name}")
    for w, name, old, new, marker in EDITS:
        if w != wid:
            continue
        code = nodes[name]["parameters"]["jsCode"]
        if marker in code:
            continue  # уже применено
        if old in code:
            nodes[name]["parameters"]["jsCode"] = code.replace(old, new, 1)
            changed.append(f"edit:{name}")
            continue
        # ни старого, ни нового — состояние неизвестно, молча портить нельзя
        raise RuntimeError(f"{wid}/{name}: не найден ни старый якорь, ни маркер результата")
    return changed


def selfcheck(wid: str, wf: dict) -> None:
    nodes = {n["name"]: n for n in wf["nodes"]}
    for name in INJECT[wid]:
        code = nodes[name]["parameters"]["jsCode"]
        assert has_resolve_user_definition(code), f"{wid}/{name}: нет определения resolveUser"
        assert code.count("resolveUser(") >= 1, f"{wid}/{name}: resolveUser не вызывается"
    for w, name, _old, _new, marker in EDITS:
        if w != wid:
            continue
        assert marker in nodes[name]["parameters"]["jsCode"], f"{wid}/{name}: патч не на месте"
    if wid == "demo-09":
        code = nodes["Валидация"]["parameters"]["jsCode"]
        assert "|| 'аноним'" not in code and "'аноним'" not in code, (
            "demo-09/Валидация: анонимный фолбэк вернулся"
        )


def main() -> int:
    push = "--push-db" in sys.argv
    wfs: dict[str, dict] = {}
    for wid, fname in FILES.items():
        wf = json.loads((BASE / fname).read_text(encoding="utf-8"))
        changed = patch_workflow(wid, wf)
        selfcheck(wid, wf)
        wfs[wid] = wf
        (BASE / fname).write_text(json.dumps(wf, ensure_ascii=False), encoding="utf-8")
        out = json.dumps(wf, ensure_ascii=False)
        assert "__BOT_TOKEN__" in out and "__SIGN_SECRET__" in out, f"{wid}: плейсхолдеры потеряны"
        for leak in ("AAH", "cd8b30b650f89cebc61e88"):
            assert leak not in out, f"{wid}: похоже, просочился секрет ({leak})"
        print(f"{wid}: identity OK" + (f" ({', '.join(changed)})" if changed else " (без изменений)"))
    if push:
        from stand.deploy_db import load_env_secrets, push_to_db  # noqa: PLC0415

        push_to_db(wfs, load_env_secrets())
        print("БД залита; перезапустите n8n для регистрации вебхуков")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
