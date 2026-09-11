# Патч demo-09 (идемпотентный): уточнение темы (needs_clarification), дата консультации
# (demo/lead_date), исходный текст заявки (source_msg). Запуск НА CT100:
#   python3 stand/patch-clarify.py            # JSON + БД
#   python3 stand/patch-clarify.py . --json-only   # только JSON (локально)
import json, sqlite3, sys

BASE = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith('-') else '/root/n8n-demo-bot'
JSON_ONLY = '--json-only' in sys.argv

wf = json.load(open(BASE + '/stand/demo-09-ai-classifier.json', encoding='utf-8'))
by_name = {n['name']: n for n in wf['nodes']}

if 'Webhook lead_date' not in by_name:
    # 1) LLM prompt: новые поля
    llm = by_name['LLM']['parameters']['jsonBody']
    old_sys = 'Ты — маршрутизатор заявок в IT-студии. Ответь СТРОГО одним JSON: {"category": одно из ["разработка","интеграция","бот","данные","прочее"], "priority": одно из ["низкий","средний","высокий"], "summary": "краткое резюме до 100 символов", "is_request": true только если это заявка на работу или услугу, false если вопрос или болтовня}. Никакого текста кроме JSON.'
    new_sys = 'Ты — маршрутизатор заявок в IT-студии. Ответь СТРОГО одним JSON: {"category": одно из ["разработка","интеграция","бот","данные","прочее"], "priority": одно из ["низкий","средний","высокий"], "summary": "краткое резюме до 100 символов", "is_request": true только если это заявка на работу или услугу, false если вопрос или болтовня, "needs_clarification": true если это похоже на заявку, но непонятно ЧТО конкретно нужно сделать (нет предмета работы/задачи), иначе false, "clarify_question": "один короткий уточняющий вопрос по существу (обязателен при needs_clarification=true, иначе пустая строка)"}. Никакого текста кроме JSON.'
    assert old_sys in llm, 'LLM system prompt not found'
    by_name['LLM']['parameters']['jsonBody'] = llm.replace(old_sys, new_sys)

    # 2) Разбор ответа: дефолты новых полей
    razbor = by_name['Разбор ответа']['parameters']['jsCode']
    old_rb = "parsed = { category: 'прочее', priority: 'средний', summary: 'не удалось разобрать ответ модели', is_request: true }; }"
    new_rb = "parsed = { category: 'прочее', priority: 'средний', summary: 'не удалось разобрать ответ модели', is_request: true, needs_clarification: false, clarify_question: '' }; }\nparsed.needs_clarification = parsed.needs_clarification === true;\nparsed.clarify_question = String(parsed.clarify_question || '');"
    assert old_rb in razbor, 'razbor anchor not found'
    by_name['Разбор ответа']['parameters']['jsCode'] = razbor.replace(old_rb, new_rb)

    # 3) Лид-захват: скип при needs_clarification, source_msg, date
    lead = by_name['Лид-захват']['parameters']['jsCode']
    old_l1 = "if ($json.is_request === false) { return [{ json: { ...$json, lead_saved: false } }]; }"
    new_l1 = "if ($json.is_request === false || $json.needs_clarification === true) { return [{ json: { ...$json, lead_saved: false } }]; }"
    old_l2 = "  user: src.user, text: String(src.text || '').slice(0, 200),\n  category: $json.category, priority: $json.priority, summary: $json.summary,\n  ts: new Date().toISOString(),\n});"
    new_l2 = "  user: src.user, text: String(src.text || '').slice(0, 200),\n  source_msg: String(src.text || '').slice(0, 1000),\n  category: $json.category, priority: $json.priority, summary: $json.summary,\n  date: null,\n  ts: new Date().toISOString(),\n});"
    assert old_l1 in lead and old_l2 in lead, 'lead anchors not found'
    by_name['Лид-захват']['parameters']['jsCode'] = lead.replace(old_l1, new_l1).replace(old_l2, new_l2)

    # 4) Новая ветка: Webhook demo/lead_date -> Присвоить дату -> Ответ lead_date
    wf['nodes'].append({
        'parameters': {'httpMethod': 'POST', 'path': 'lead_date', 'responseMode': 'responseNode',
                       'options': {'allowedOrigins': '*'}},
        'name': 'Webhook lead_date', 'type': 'n8n-nodes-base.webhook', 'typeVersion': 2,
        'webhookId': 'demo-lead-date', 'id': 'auto-lead-date-hook', 'position': [1300, 620]})
    wf['nodes'].append({
        'parameters': {'jsCode': "const staticData = $getWorkflowStaticData('global');\nstaticData.leads = staticData.leads || [];\nconst body = $input.first().json.body || {};\nconst user = String(body.user || '');\nconst date = String(body.date || '');\nif (!user || !date) { return [{ json: { ok: false, error: 'user and date required' } }]; }\nfor (let i = staticData.leads.length - 1; i >= 0; i--) {\n  const l = staticData.leads[i];\n  if (l.user === user && !l.date) { l.date = date; return [{ json: { ok: true, lead: l } }]; }\n}\nreturn [{ json: { ok: false, error: 'нет открытой заявки' } }];"},
        'name': 'Присвоить дату', 'type': 'n8n-nodes-base.code', 'typeVersion': 2,
        'id': 'auto-lead-date-set', 'position': [1520, 620]})
    wf['nodes'].append({
        'parameters': {'respondWith': 'json', 'responseBody': '={{ JSON.stringify($json) }}'},
        'name': 'Ответ lead_date', 'type': 'n8n-nodes-base.respondToWebhook', 'typeVersion': 1.1,
        'id': 'auto-lead-date-resp', 'position': [1740, 620]})
    wf['connections']['Webhook lead_date'] = {'main': [[{'node': 'Присвоить дату', 'type': 'main', 'index': 0}]]}
    wf['connections']['Присвоить дату'] = {'main': [[{'node': 'Ответ lead_date', 'type': 'main', 'index': 0}]]}

assert 'Webhook leads' in wf['connections']

if JSON_ONLY:
    json.dump(wf, open(BASE + '/stand/demo-09-ai-classifier.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=2)
    print('json-only saved')
    sys.exit(0)

nodes = json.dumps(wf['nodes'], ensure_ascii=False)
conns = json.dumps(wf['connections'], ensure_ascii=False)
db = sqlite3.connect('/root/n8n/data/database.sqlite')
rows = db.execute("SELECT id, name, activeVersionId FROM workflow_entity").fetchall()
target = [r for r in rows if r[0] == 'demo-09']
assert len(target) == 1, target
wid, name, avid = target[0]
assert avid, 'demo-09 не активирован'
db.execute("UPDATE workflow_entity SET nodes=?, connections=? WHERE id=?", (nodes, conns, wid))
db.execute("UPDATE workflow_history SET nodes=?, connections=? WHERE versionId=?", (nodes, conns, avid))
hook = db.execute("SELECT method, webhookPath FROM webhook_entity WHERE workflowId=? AND webhookPath='lead_date'", (wid,)).fetchall()
if not hook:
    db.execute("INSERT INTO webhook_entity (workflowId, webhookPath, method, node, webhookId, pathLength) VALUES (?,?,?,?,?,?)",
               (wid, 'lead_date', 'POST', 'Webhook lead_date', 'demo-lead-date', 1))
db.commit(); db.close()
print('patched', wid, name)
