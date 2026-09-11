import json, sqlite3
wf = json.load(open('/root/n8n-demo-bot/stand/demo-09-ai-classifier.json'))
nodes = json.dumps(wf['nodes'], ensure_ascii=False)
conns = json.dumps(wf['connections'], ensure_ascii=False)
db = sqlite3.connect('/root/n8n/data/database.sqlite')
rows = db.execute("SELECT id, name, activeVersionId FROM workflow_entity").fetchall()
print('workflows:', [(r[0], r[1]) for r in rows])
target = [r for r in rows if r[0] == 'demo-09']
assert len(target) == 1, target
wid, name, avid = target[0]
assert avid, 'demo-09 не активирован'
db.execute("UPDATE workflow_entity SET nodes=?, connections=? WHERE id=?", (nodes, conns, wid))
n = db.execute("UPDATE workflow_history SET nodes=?, connections=? WHERE versionId=?", (nodes, conns, avid)).rowcount
db.commit(); db.close()
print('patched', wid, name, 'history rows:', n)
