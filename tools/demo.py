#!/usr/bin/env python3
"""Run the viewer on made-up sessions. Nothing here reads your real data.

    python3 tools/demo.py                 # sources already enabled and indexed
    python3 tools/demo.py --first-run     # sources found, nothing enabled yet

Builds a pretend home folder with sample stores for each supported app, then
starts the viewer against it on its own port and data folder. Use it to try
the app, test a change, or take screenshots that are safe to share.
"""
import argparse
import json
import random
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RNG = random.Random(7)
START = datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc)

PROJECTS = {
    'garden-planner': [
        ('Plan the garden planner data model', 'beds, plants and a seed calendar'),
        ('Add a seed calendar view to the garden planner', 'a month grid that shows sowing windows'),
        ('Garden planner: frost date lookup', 'last and first frost dates by region'),
        ('Fix the garden planner bed overlap bug', 'two beds can share the same square'),
        ('Garden planner: companion planting hints', 'show which plants do well together'),
        ('Export the garden planner as a printable page', 'a one-page plan for the shed wall'),
        ('Garden planner: watering reminders', 'a weekly reminder list by bed'),
    ],
    'recipe-box': [
        ('Import recipes from plain text files', 'parse title, ingredients and steps'),
        ('Scale a recipe up or down', 'convert quantities and keep sensible units'),
        ('Recipe box: search by ingredient', 'find what I can cook from the pantry'),
        ('Add a weekly meal plan page', 'seven days, drag recipes into slots'),
        ('Recipe box: shopping list from a meal plan', 'merge duplicate ingredients'),
    ],
    'bike-route-map': [
        ('Draw a route from a GPX file', 'show the line and the climb profile'),
        ('Bike route map: estimate ride time', 'use distance and elevation gain'),
        ('Mark water stops on the route', 'pins with a short note each'),
        ('Bike route map: offline tiles', 'cache map tiles for a planned ride'),
    ],
    'reading-log': [
        ('Start a reading log app', 'books, dates and a short note'),
        ('Reading log: yearly summary', 'pages read per month as a bar chart'),
        ('Add tags to the reading log', 'filter books by tag'),
        ('Reading log: import from a spreadsheet', 'map columns and skip duplicates'),
    ],
    'weather-station': [
        ('Read the weather station sensor', 'temperature and humidity every minute'),
        ('Weather station: daily highs and lows', 'store one summary row per day'),
        ('Chart a week of weather station data', 'a small line chart per sensor'),
    ],
}
MODELS = {'claude': 'sample-large', 'codex': 'sample-coder', 't3': 'sample-large',
          'opencode': 'sample-fast', 'grok': 'sample-reasoner'}
FILES = ['models.py', 'calendar.py', 'views.py', 'store.py', 'README.md', 'tests/test_core.py', 'static/app.css']
FOLLOWUPS = ['Looks good. Can you add a test for the empty case?',
             'Nice. Keep the names short and explain the tricky part in the README.',
             'That works. What would break if the input file is missing?',
             'Good. Show me the smallest version first, then we can grow it.']


def iso(t):
    return t.isoformat().replace('+00:00', 'Z')


def script(title, detail, project):
    """One made-up conversation: (role, text) and ('tool', dict) steps."""
    f1, f2 = RNG.sample(FILES, 2)
    code = (f"```python\ndef {project.replace('-', '_')}_step(items):\n"
            f"    \"\"\"{detail.capitalize()}.\"\"\"\n"
            "    seen = set()\n    for item in items:\n        if item.key in seen:\n            continue\n"
            "        seen.add(item.key)\n        yield item\n```")
    steps = [
        ('user', f"{title}.\n\nWhat I want: {detail}. Keep it small and easy to read. "
                 "Tell me your plan before you change files."),
        ('assistant', f"Here is the plan.\n\nFirst I will read `{f1}` to see what exists. Then I will add the "
                      f"smallest piece that gives you {detail}. Last, I will run the tests and show you the result."),
        ('tool', {'name': 'Read', 'input': {'file_path': f'{project}/{f1}'}}),
        ('tool', {'result': f'# {f1}\n# 84 lines. Sample content for the demo.\n'}),
        ('tool', {'name': 'Bash', 'input': {'command': 'python3 -m unittest -q'}}),
        ('tool', {'result': 'Ran 12 tests in 0.31s\n\nOK'}),
        ('tool', {'name': 'Edit', 'input': {'file_path': f'{project}/{f2}', 'summary': detail}}),
        ('tool', {'result': f'Updated {f2}'}),
        ('assistant', f"Done. The change lives in `{f2}`.\n\n{code}\n\nThe tests pass. One thing to know: "
                      "items with the same key are skipped, so the first one wins."),
        ('user', RNG.choice(FOLLOWUPS)),
        ('tool', {'name': 'Bash', 'input': {'command': 'python3 -m unittest -q'}}),
        ('tool', {'result': 'Ran 13 tests in 0.34s\n\nOK'}),
        ('assistant', "Added. There are 13 tests now and they all pass. I also wrote two plain sentences in the "
                      "README about the tricky part, so the next reader does not have to guess."),
    ]
    return steps


def schedule():
    """Spread every topic over about five months, then deal them out to apps."""
    topics = [(p, t, d) for p, items in PROJECTS.items() for t, d in items]
    apps = ['claude'] * 9 + ['codex'] * 7 + ['t3'] * 4 + ['opencode'] * 3 + ['grok'] * 2 + ['cursor'] * 2
    RNG.shuffle(apps)
    out = []
    for n, (project, title, detail) in enumerate(topics):
        when = START + timedelta(days=n * 6.5 + RNG.random() * 3, minutes=RNG.randrange(600))
        out.append((apps[n % len(apps)], project, title, detail, when))
    return out


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')


def build(home):
    code = home / 'code'
    t3_rows, n = [], 0
    for app, project, title, detail, when in schedule():
        n += 1
        cwd = str(code / project)
        steps = script(title, detail, project)
        times = [iso(when + timedelta(seconds=40 * i)) for i in range(len(steps))]
        sid = f'demo-{n:03d}'
        if app == 'claude':
            rows = [{'type': 'summary', 'summary': title, 'sessionId': sid, 'cwd': cwd}]
            for (role, body), at in zip(steps, times):
                if role == 'tool':
                    part = ({'type': 'tool_use', 'name': body['name'], 'input': body['input']} if 'name' in body
                            else {'type': 'tool_result', 'content': body['result']})
                    rows.append({'type': 'assistant', 'sessionId': sid, 'cwd': cwd, 'timestamp': at, 'uuid': f'{sid}-{at}',
                                 'message': {'model': MODELS[app], 'content': [part]}})
                else:
                    rows.append({'type': role, 'sessionId': sid, 'cwd': cwd, 'timestamp': at, 'uuid': f'{sid}-{at}',
                                 'message': {'model': MODELS[app], 'content': body}})
            write_jsonl(home / '.claude/projects' / project / f'{sid}.jsonl', rows)
        elif app == 'codex':
            rows = [{'type': 'session_meta', 'timestamp': times[0], 'payload': {'id': sid, 'cwd': cwd, 'timestamp': times[0]}},
                    {'type': 'turn_context', 'timestamp': times[0], 'payload': {'model': MODELS[app]}}]
            for (role, body), at in zip(steps, times):
                if role == 'tool':
                    item = ({'type': 'function_call', 'name': body['name'], 'arguments': json.dumps(body['input'])} if 'name' in body
                            else {'type': 'function_call_output', 'output': body['result']})
                else:
                    item = {'type': 'message', 'role': role, 'content': body}
                rows.append({'type': 'response_item', 'timestamp': at, 'payload': item})
            write_jsonl(home / '.codex/sessions' / when.strftime('%Y/%m/%d') / f'rollout-{sid}.jsonl', rows)
        elif app == 't3':
            t3_rows.append((sid, cwd, title, steps, times))
        elif app == 'opencode':
            storage = home / '.local/share/opencode/storage'
            ms = lambda s: int(datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp() * 1000)
            files = {f'session/{project}/{sid}.json': {'id': sid, 'title': title, 'directory': cwd,
                                                       'time': {'created': ms(times[0]), 'updated': ms(times[-1])}}}
            for i, ((role, body), at) in enumerate(zip(steps, times)):
                mid = f'{sid}-m{i:02d}'
                files[f'message/{sid}/{mid}.json'] = {'id': mid, 'role': 'user' if role == 'user' else 'assistant',
                                                     'time': {'created': ms(at)}}
                files[f'part/{mid}/p.json'] = ({'type': 'tool', 'name': body.get('name', 'result'), 'state': body}
                                               if role == 'tool' else {'type': 'text', 'text': body})
            for rel, data in files.items():
                path = storage / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(data), encoding='utf-8')
        elif app == 'grok':
            folder = home / '.grok/sessions' / sid
            rows = []
            for (role, body), at in zip(steps, times):
                if role == 'tool':
                    rows.append({'type': 'tool_result', 'timestamp': at, 'content': body.get('result') or json.dumps(body)})
                else:
                    rows.append({'type': role, 'timestamp': at, 'content': body, 'model_id': MODELS[app]})
            write_jsonl(folder / 'chat_history.jsonl', rows)
            (folder / 'summary.json').write_text(json.dumps({
                'generated_title': title, 'created_at': times[0], 'updated_at': times[-1],
                'current_model_id': MODELS[app], 'info': {'cwd': cwd}}), encoding='utf-8')
        else:
            write_jsonl(home / '.cursor/projects' / project / f'{sid}.jsonl',
                        [{'role': role, 'message': {'content': [{'type': 'text', 'text': body}]}}
                         for role, body in steps if role != 'tool'])

    # T3 Code: one database. The first thread hands two pieces of work to child threads.
    db = home / '.t3/userdata/statev2.sqlite'
    db.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(db)
    c.execute('CREATE TABLE projection_projects(project_id,workspace_root)')
    c.execute('CREATE TABLE orchestration_v2_projection_threads(thread_id,project_id,title,default_provider,created_at,updated_at,payload_json)')
    c.execute('CREATE TABLE orchestration_v2_projection_messages(thread_id,message_id,role,created_at,payload_json)')
    c.execute('CREATE TABLE orchestration_v2_projection_turn_items(thread_id,type,ordinal,updated_at,payload_json)')
    def thread(tid, cwd, title, steps, times, parent=''):
        c.execute('INSERT OR IGNORE INTO projection_projects VALUES(?,?)', (cwd, cwd))
        c.execute('INSERT INTO orchestration_v2_projection_threads VALUES(?,?,?,?,?,?,?)',
                  (tid, cwd, title, 'sample', times[0], times[-1],
                   json.dumps({'lineage': {'parentThreadId': parent}, 'modelSelection': {'model': MODELS['t3']}})))
        for i, ((role, body), at) in enumerate(zip(steps, times)):
            if role == 'tool':
                item = ({'type': 'command_execution', 'input': body['input'], 'startedAt': at} if 'name' in body
                        else {'type': 'command_execution', 'output': body['result'], 'startedAt': at})
                c.execute('INSERT INTO orchestration_v2_projection_turn_items VALUES(?,?,?,?,?)', (tid, 'tool', i, at, json.dumps(item)))
            else:
                c.execute('INSERT INTO orchestration_v2_projection_messages VALUES(?,?,?,?,?)', (tid, f'{tid}-{i:02d}', role, at, json.dumps({'text': body})))
    for i, (sid, cwd, title, steps, times) in enumerate(t3_rows):
        thread(sid, cwd, title, steps, times)
        if i == 0:
            project = Path(cwd).name
            for k, (sub, detail) in enumerate([('Write the tests', 'tests for the new piece'), ('Review the change', 'a second read of the diff')]):
                at = datetime.fromisoformat(times[3].replace('Z', '+00:00')) + timedelta(minutes=2 + k)
                sub_steps = script(f'{sub}: {title[0].lower()}{title[1:]}', detail, project)[:9]
                thread(f'{sid}-child-{k + 1}', cwd, f'{sub}: {title[0].lower()}{title[1:]}', sub_steps,
                       [iso(at + timedelta(seconds=35 * j)) for j in range(len(sub_steps))], parent=sid)
    c.commit()
    c.close()

    write_jsonl(home / '.codex/history.jsonl',
                [{'session_id': 'demo-history', 'ts': int((START + timedelta(days=9 * i)).timestamp()), 'text': t + '.'}
                 for i, (t, _) in enumerate(PROJECTS['recipe-box'])])
    (home / '.gemini').mkdir(parents=True, exist_ok=True)   # shows the "found, not yet supported" state

    # Official-export-shaped ZIPs, ready for the Import flow.
    downloads = home / 'Downloads'
    downloads.mkdir(parents=True, exist_ok=True)
    day = START + timedelta(days=40)
    claude_ai = [{'uuid': f'demo-cloud-{i}', 'name': t, 'created_at': iso(day + timedelta(days=11 * i)), 'chat_messages': [
        {'sender': 'human', 'created_at': iso(day + timedelta(days=11 * i)), 'text': f'{t}. Where should I start?'},
        {'sender': 'assistant', 'created_at': iso(day + timedelta(days=11 * i, seconds=30)),
         'text': f'Start with {d}. Write down three examples by hand first, then build the smallest thing that handles them.'}]}
        for i, (t, d) in enumerate(PROJECTS['reading-log'])]
    chatgpt = [{'id': f'demo-chat-{i}', 'title': t, 'create_time': (day + timedelta(days=13 * i)).timestamp(), 'mapping': {
        'a': {'message': {'author': {'role': 'user'}, 'create_time': (day + timedelta(days=13 * i)).timestamp(),
                          'content': {'parts': [f'{t}. Give me a short plan.']}}},
        'b': {'message': {'author': {'role': 'assistant'}, 'create_time': (day + timedelta(days=13 * i, seconds=20)).timestamp(),
                          'metadata': {'model_slug': 'sample-chat'},
                          'content': {'parts': [f'A short plan for {d}: collect a sample, sketch the output, then write it in one small file.']}}}}}
        for i, (t, d) in enumerate(PROJECTS['weather-station'])]
    for name, data in (('claude-export.zip', claude_ai), ('chatgpt-export.zip', chatgpt)):
        with zipfile.ZipFile(downloads / name, 'w') as z:
            z.writestr('conversations.json', json.dumps(data))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--dir', default=str(Path(tempfile.gettempdir()) / 'lej-archive-demo'), help='where the pretend home and demo index go (rebuilt each run)')
    p.add_argument('--port', type=int, default=8799)
    p.add_argument('--first-run', action='store_true', help='leave every source turned off, as on a new install')
    p.add_argument('--build-only', action='store_true', help='write the demo files and exit')
    a = p.parse_args()
    root = Path(a.dir)
    if root.exists():
        if not (root / '.lej-demo').exists():
            sys.exit(f'{root} exists and was not made by this script. Pick another --dir.')
        shutil.rmtree(root)
    home, data = root / 'home/sam', root / 'app-data'
    home.mkdir(parents=True)
    data.mkdir()
    (root / '.lej-demo').write_text('Made by tools/demo.py. Safe to delete.\n')
    build(home)
    kinds = [('claude', '.claude'), ('codex', '.codex'), ('t3', '.t3/userdata/statev2.sqlite'),
             ('opencode', '.local/share/opencode'), ('cursor', '.cursor'),
             ('cursor_app', 'Library/Application Support/Cursor'), ('grok', '.grok'), ('gemini', '.gemini')]
    supported = {'claude', 'codex', 't3', 'opencode', 'cursor', 'grok'}
    config = {'sources': [{'id': str(i), 'kind': k, 'path': str(home / rel), 'enabled': k in supported and not a.first_run}
                          for i, (k, rel) in enumerate(kinds)],
              'tags': {} if a.first_run else {'garden': ['garden planner', 'seed calendar'], 'recipes': ['recipe box', 'meal plan']}}
    (data / 'config.json').write_text(json.dumps(config, indent=2), encoding='utf-8')
    print(f'Demo files: {root}\nExport ZIPs to try the import flow: {home / "Downloads"}', flush=True)
    if a.build_only:
        return
    # Index once before serving, so the demo opens with sessions already there.
    if not a.first_run:
        sys.path.insert(0, str(REPO))
        import viewer
        store = viewer.Store(argparse.Namespace(data_dir=str(data)))
        store.lock.acquire()
        store.refresh()
    try:
        subprocess.run([sys.executable, str(REPO / 'viewer.py'), '--data-dir', str(data), '--port', str(a.port)])
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
