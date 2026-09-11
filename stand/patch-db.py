"""Патч demo-09/demo-10 на CT100: обновить ноды/связи + зарегистрировать новые вебхуки.
Запуск: python3 patch-db.py /root/n8n-demo-bot/stand. Рестарт контейнера — снаружи."""
import json
import sqlite3
import sys

stand = sys.argv[1] if len(sys.argv) > 1 else '/root/n8n-demo-bot/stand'
db = sqlite3.connect('/root/n8n/data/database.sqlite')
cur = db.cursor()

jobs = {
    'demo-09': ('demo-09-ai-classifier.json', [('demo/leads', 'Webhook leads', 'demo-leads')]),
    'demo-10': ('demo-10-booking.json', [('demo/my', 'Webhook my', 'demo-my'), ('demo/cancel', 'Webhook cancel', 'demo-cancel')]),
}

for wf_id, (fname, hooks) in jobs.items():
    wf = json.load(open(f'{stand}/{fname}', encoding='utf-8'))
    nodes_s = json.dumps(wf['nodes'], ensure_ascii=False)
    conn_s = json.dumps(wf['connections'], ensure_ascii=False)
    # контроль: все связи указывают на существующие ноды
    names = {n['name'] for n in wf['nodes']}
    for src, c in wf['connections'].items():
        assert src in names, (wf_id, src)
        for row in (c.get('main') or []):
            for t in (row or []):
                assert t['node'] in names, (wf_id, t['node'])
    cur.execute('UPDATE workflow_entity SET nodes=?, connections=? WHERE id=?', (nodes_s, conn_s, wf_id))
    assert cur.rowcount == 1, wf_id
    # активная версия в истории — тоже ноды/связи
    cur.execute(
        "UPDATE workflow_history SET nodes=?, connections=? WHERE workflowId=? AND versionId="
        "(SELECT activeVersionId FROM workflow_entity WHERE id=?)", (nodes_s, conn_s, wf_id, wf_id))
    # регистрируем вебхуки (idempotent)
    for path, node, whid in hooks:
        cur.execute('DELETE FROM webhook_entity WHERE workflowId=? AND webhookPath=?', (wf_id, path))
        cur.execute(
            'INSERT INTO webhook_entity (workflowId, webhookPath, method, node, webhookId, pathLength) VALUES (?,?,?,?,?,?)',
            (wf_id, path, 'POST', node, whid, len(path)))
    print(wf_id, 'patched, hooks:', [h[0] for h in hooks])

db.commit()
# финальная сверка
for wf_id in jobs:
    row = cur.execute('SELECT nodes FROM workflow_entity WHERE id=?', (wf_id,)).fetchone()
    json.loads(row[0])
    print(wf_id, 'verified in DB')
db.close()
