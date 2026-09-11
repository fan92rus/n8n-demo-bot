#!/usr/bin/env python3
"""Диагностика demo-09: что реально исполнилось в последних запусках."""
import json
import sqlite3


def unwrap(x):
    while isinstance(x, str):
        try:
            x = json.loads(x)
        except Exception:
            return x
    return x


con = sqlite3.connect("/root/n8n/data/database.sqlite")
rows = con.execute(
    "select e.id, e.status, e.startedAt, d.data from execution_entity e "
    "join execution_data d on d.executionId=e.id "
    "where e.workflowId='demo-09' order by e.id desc limit 3"
).fetchall()
for eid, status, ts, data in rows:
    res = unwrap(data)
    if isinstance(res, list):
        res = unwrap(res[0]) if res else {}
    rd = res.get("resultData", {}) if isinstance(res, dict) else {}
    rd = unwrap(rd).get("runData", {}) if isinstance(rd, dict) else {}
    rd = unwrap(rd)
    print("exec", eid, status, ts, "| nodes:", list(rd.keys()))
    if isinstance(rd, dict):
        for node, runs in rd.items():
            for r in runs:
                if isinstance(r, dict) and r.get("error"):
                    print("  FAIL:", node, "->", json.dumps(r["error"], ensure_ascii=False)[:300])
con.close()
