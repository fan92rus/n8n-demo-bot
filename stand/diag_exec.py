#!/usr/bin/env python3
"""Диагностика demo-09 (или любого воркфлоу): что исполнилось в последних запусках.

Данные execution_data в n8n хранятся в flatted-формате — сначала декодируем.
Запуск на CT100 из корня репо:
  python3 stand/diag_exec.py [workflowId] [limit]
Секреты (init_data, токены) в вывод не печатаются.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stand.flatted import loads as flatted_loads  # noqa: E402


def main() -> int:
    wid = sys.argv[1] if len(sys.argv) > 1 else "demo-09"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    con = sqlite3.connect("/root/n8n/data/database.sqlite")
    rows = con.execute(
        "select e.id, e.status, e.startedAt, d.data from execution_entity e "
        "join execution_data d on d.executionId=e.id "
        "where e.workflowId=? order by e.id desc limit ?",
        (wid, limit),
    ).fetchall()
    for eid, status, ts, data in rows:
        try:
            res = flatted_loads(data)
        except Exception as e:  # noqa: BLE001
            print("exec", eid, status, ts, "| DECODE FAIL:", e)
            continue
        rd = (res.get("resultData") or {}).get("runData") or {}
        print("exec", eid, status, ts, "| nodes:", list(rd.keys()))
        for node, runs in rd.items():
            for r in runs or []:
                if isinstance(r, dict) and r.get("error"):
                    err = r["error"]
                    msg = err.get("message") if isinstance(err, dict) else err
                    print("  FAIL:", node, "->", str(msg)[:300])
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
