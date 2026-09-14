"""Общая заливка воркфлоу в БД CT100 для патч-скриптов с --push-db.

Правила (см. ТЗ деплоя):
  - workflow_entity.nodes/connections — строго JSON-массив/объект, active=1;
  - workflow_history обновляется ПО activeVersionId (версия, что реально активна);
  - секреты подставляются из /root/n8n-demo-bot.env только при заливке, в
    локальные JSON (репозиторий) не попадают.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

ENV_FILE = Path("/root/n8n-demo-bot.env")


def load_env_secrets() -> dict:
    env = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    assert env.get("BOT_TOKEN"), "BOT_TOKEN не найден в /root/n8n-demo-bot.env"
    assert env.get("DEMO_SIGN_SECRET"), "DEMO_SIGN_SECRET не найден в /root/n8n-demo-bot.env"
    return {"__BOT_TOKEN__": env["BOT_TOKEN"], "__SIGN_SECRET__": env["DEMO_SIGN_SECRET"]}


def substitute_workflow(wf: dict, secrets: dict) -> tuple[str, str]:
    """nodes/connections со вставленными секретами (плейсхолдеры уходят)."""
    nodes = json.dumps(wf["nodes"], ensure_ascii=False)
    conns = json.dumps(wf["connections"], ensure_ascii=False)
    for ph, val in secrets.items():
        nodes = nodes.replace(ph, val)
        conns = conns.replace(ph, val)
    assert isinstance(json.loads(nodes), list), "nodes не массив"
    assert "__BOT_TOKEN__" not in nodes and "__SIGN_SECRET__" not in nodes, (
        "плейсхолдер не подставился"
    )
    return nodes, conns


def push_to_db(wfs: dict[str, dict], secrets: dict) -> None:
    """Залить воркфлоу: entity (active=1) + история по activeVersionId."""
    con = sqlite3.connect("/root/n8n/data/database.sqlite")
    try:
        for wid, wf in wfs.items():
            nodes, conns = substitute_workflow(wf, secrets)
            cur = con.execute(
                "update workflow_entity set nodes=?, connections=?, active=1 where id=?",
                (nodes, conns, wid),
            )
            assert cur.rowcount == 1, f"{wid}: workflow_entity не найдена"
            avid = con.execute(
                "select activeVersionId from workflow_entity where id=?", (wid,)
            ).fetchone()[0]
            assert avid, f"{wid}: нет activeVersionId"
            n = con.execute(
                "update workflow_history set nodes=?, connections=? where versionId=?",
                (nodes, conns, avid),
            ).rowcount
            assert n == 1, f"{wid}: история по activeVersionId не обновлена (rows={n})"
            print(f"{wid}: залито в БД (entity активна + история {avid[:8]})")
        con.commit()
    finally:
        con.close()
