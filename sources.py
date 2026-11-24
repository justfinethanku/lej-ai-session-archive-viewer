"""Source discovery, portable paths and local-only import adapters."""
import contextlib
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath, PurePosixPath
import sqlite3
import sys
import threading

DATABASE_LOCK = threading.RLock()
import uuid
import zipfile

KINDS = {'claude': 'Claude Code', 'codex': 'Codex', 't3': 'T3 Code',
         'opencode': 'OpenCode', 'cursor': 'Cursor transcript files',
         'grok': 'Grok CLI', 'gemini': 'Gemini CLI', 'antigravity': 'Antigravity',
         'cursor_app': 'Cursor app store', 'claude_ai': 'Claude.ai / Claude desktop export', 'chatgpt': 'ChatGPT export'}
PARSERS = {'claude', 'codex', 't3', 'opencode', 'cursor', 'grok', 'claude_ai', 'chatgpt'}


def defaults(platform=None, home=None, env=None):
    platform = platform or sys.platform
    env = os.environ if env is None else env
    P = PureWindowsPath if platform == 'win32' else PurePosixPath
    h = P(home or (env.get('USERPROFILE') if platform == 'win32' else str(Path.home())) or '.')
    roaming = P(env.get('APPDATA', str(h/'AppData/Roaming')))
    local = P(env.get('LOCALAPPDATA', str(h/'AppData/Local')))
    app = roaming/'Cursor' if platform == 'win32' else h/'Library/Application Support/Cursor' if platform == 'darwin' else P(env.get('XDG_CONFIG_HOME', str(h/'.config')))/'Cursor'
    # OpenCode uses XDG data layout on all OSes; also probe Windows app-data installations.
    roots = [('claude', h/'.claude'), ('codex', h/'.codex'), ('t3', h/'.t3/userdata/statev2.sqlite'),
             ('opencode', P(env.get('XDG_DATA_HOME', str(h/'.local/share')))/'opencode'),
             ('cursor', h/'.cursor'), ('cursor_app', app), ('grok', h/'.grok'),
             ('gemini', h/'.gemini'), ('antigravity', h/'.gemini/antigravity')]
    if platform == 'win32':
        roots += [('opencode', local/'opencode'), ('t3', roaming/'t3/userdata/statev2.sqlite')]
    return [{'id': str(i), 'kind': k, 'path': str(p), 'enabled': False} for i,(k,p) in enumerate(roots)]


def app_data(platform=None, home=None, env=None):
    platform = platform or sys.platform
    env = os.environ if env is None else env
    P = PureWindowsPath if platform == 'win32' else PurePosixPath
    h = P(home or str(Path.home()))
    base = P(env.get('LOCALAPPDATA', str(h/'AppData/Local'))) if platform == 'win32' else h/'Library/Application Support' if platform == 'darwin' else P(env.get('XDG_DATA_HOME', str(h/'.local/share')))
    return base/'lej-ai-session-archive-viewer'


def load_config(cache):
    path = cache/'config.json'
    if path.exists(): return json.loads(path.read_text(encoding='utf-8'))
    config = {'sources': defaults(), 'tags': {}}
    path.write_text(json.dumps(config, indent=2), encoding='utf-8')
    return config


def version(path):
    try: return int(path.stem.rsplit('_',1)[-1])
    except ValueError: return -1


def millis(value):
    from viewer import stamp
    return stamp(value/1000 if isinstance(value, (int,float)) else value)


def block(text, role='assistant', at='', model='', tool=False):
    from viewer import text_content
    return {'text': text_content(text), 'role': 'tool' if tool else role, 'kind': 'tool' if tool else 'message', 'time': at, 'model': model or ''}


@contextlib.contextmanager
def database(path, cache):
    # Never use SQLite against the live store: copy a stable DB+WAL pair first.
    from viewer import snapshot
    with DATABASE_LOCK:
        copy = snapshot(path, cache)
        conn = sqlite3.connect(copy.as_uri()+'?mode=ro&immutable=1', uri=True)
        conn.row_factory = sqlite3.Row
        try: yield conn
        finally: conn.close()


def tables(c):
    return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def source_files(kind, root):
    if kind == 'claude':
        root = root/'projects' if (root/'projects').exists() else root
        return root.rglob('*.jsonl')
    if kind == 'cursor':
        root = root/'projects' if (root/'projects').exists() else root
        return root.rglob('*.jsonl')
    if kind == 'grok': return (root/'sessions' if (root/'sessions').exists() else root).rglob('chat_history.jsonl')
    if kind == 'codex':
        from viewer import Store
        return Store.codex_paths(root)
    if kind in ('claude_ai','chatgpt'): return [root] if root.is_file() else []
    return []


class SourceMethods:
    def save_config(self, config):
        if not isinstance(config.get('tags'), dict) or not isinstance(config.get('sources'), list): raise ValueError('Expected sources and tag rules')
        for name,keywords in config['tags'].items():
            if not name.strip() or not isinstance(keywords,list) or not keywords or any(not isinstance(k,str) or not k.strip() for k in keywords): raise ValueError('Each tag needs a name and nonempty keyword list')
        ids = set()
        for s in config['sources']:
            if s.get('kind') not in KINDS or not isinstance(s.get('path'),str) or not s['path'].strip() or s.get('id') in ids: raise ValueError('Invalid source')
            ids.add(s['id'])
            path = Path(s['path']).expanduser().resolve()
            managed = s['kind'] in ('claude_ai','chatgpt') and path.parent == (self.cache/'imports').resolve()
            if not managed and (path == self.cache.resolve() or self.cache.resolve() in path.parents or path in self.cache.resolve().parents): raise ValueError('Source and app data folders must be separate')
        temp = self.cache/'config.tmp'
        temp.write_text(json.dumps(config,indent=2),encoding='utf-8')
        os.replace(temp,self.cache/'config.json')
        self.config = config

    def discovery(self):
        results = []
        for s in self.config['sources']:
            p = Path(s['path']).expanduser()
            kind = s['kind']; found = p.exists(); supported = kind in PARSERS; count = None
            status = 'Not found'
            try:
                if found and kind in ('codex','t3','opencode'):
                    if kind == 't3':
                        with database(p,self.cache) as c:
                            count = c.execute('SELECT count(*) FROM orchestration_v2_projection_threads').fetchone()[0]
                    elif kind == 'opencode':
                        db = p/'opencode.db'
                        storage = p/'storage' if (p/'storage').exists() else p
                        legacy_ids = {json.loads(f.read_text(encoding='utf-8'))['id'] for f in (storage/'session').rglob('*.json')}
                        if not db.exists():
                            supported = bool(legacy_ids); count = len(legacy_ids) if supported else None
                        else:
                            with database(db,self.cache) as c:
                                ts = tables(c)
                                names = [t for t in ('session','session_v2') if t in ts]
                                supported = bool(names)
                                count = len(legacy_ids | {r[0] for t in names for r in c.execute('SELECT id FROM '+t)})
                    else:
                        native = set()
                        for db in p.glob('thread_history_*.sqlite'):
                            with database(db,self.cache) as c:
                                if not tables(c) & {'thread_items','thread_realtime_items','thread_turns'}: raise ValueError('Unknown Codex history schema')
                                for t in ('thread_items','thread_realtime_items','thread_turns'):
                                    if t in tables(c): native.update(r[0] for r in c.execute('SELECT DISTINCT thread_id FROM '+t))
                        # Count files by reading session IDs, so DB migrations do not double count.
                        from viewer import records
                        file_ids = set()
                        history = 0
                        for f in source_files(kind,p):
                            if f.name == 'history.jsonl': history = 1; continue
                            native_id = None
                            for r in records(f,[]):
                                if r.get('type') == 'session_meta':
                                    m = r.get('payload') or {}; native_id = m.get('id') or m.get('session_id'); break
                            file_ids.add(native_id or str(f))
                        count = len(native | file_ids) + history
                elif found and supported:
                    count = sum(1 for _ in source_files(kind,p)) if kind not in ('claude_ai','chatgpt') else len(json.loads(p.read_text(encoding='utf-8')))
                status = 'Supported' if found and supported else 'Found, not yet supported' if found else 'Not found'
            except Exception as e:
                supported = False; status = 'Found, not yet supported ('+type(e).__name__+')'
            results.append(dict(s, name=KINDS[kind], supported=supported, status=status, count=count))
        if not self.status.get('busy'):
            from viewer import expire_snapshots
            expire_snapshots(self.cache)
        for kind in ('claude_ai','chatgpt'):
            results.append({'id':kind,'kind':kind,'name':KINDS[kind],'path':'Official export ZIP','enabled':False,'supported':False,'status':'Import data export — no local transcripts','count':None})
        return {'sources':results,'config':self.config,'kinds':{k:v for k,v in KINDS.items() if k in PARSERS and k not in ('claude_ai','chatgpt')}}

    def put(self, source, native, meta, blocks, namespace=''):
        sid = source + ':' + namespace + str(native)
        values = dict(id=sid,source=source,title='',project='',start='',end='',count=0,model='',parent='',native_id=str(native))
        values.update({k:v for k,v in meta.items() if v is not None})
        with self.connect() as c:
            c.execute('DELETE FROM blocks WHERE session=?',(sid,))
            for b in blocks:
                if not b['text']: continue
                self.add_block(c,sid,b)
                values['count'] += b['kind']=='message'
                values['start'] = min(values['start'] or b['time'], b['time']) if b['time'] else values['start']
                values['end'] = max(values['end'],b['time'])
                if not values['title'] and b['role']=='user': values['title']=b['text'][:180]
            values['title'] = values['title'] or 'Untitled session'
            c.execute('INSERT OR REPLACE INTO sessions VALUES(:id,:source,:title,:project,:start,:end,:count,:model,:parent,:native_id)',values)
        self.tag_dirty.add(sid)

    def refresh_sources(self):
        # Disabled sources disappear immediately on refresh, including their searchable text.
        with self.connect() as c:
            c.execute('DELETE FROM blocks');c.execute('DELETE FROM sessions');c.execute('DELETE FROM files');c.execute('DELETE FROM tags')
        self.primary_codex = set()
        for s in self.config['sources']:
            if not s['enabled']: continue
            root = Path(s['path']).expanduser().resolve(); kind = s['kind']
            if not root.exists():
                self.status['warnings'].append(KINDS[kind]+': source missing'); continue
            self.status['phase']='Indexing '+KINDS[kind]
            try:
                if kind == 't3':
                    self.args.t3 = str(root)
                    with database(root,self.cache) as c: self.index_t3(Path(c.execute('PRAGMA database_list').fetchone()[2]))
                elif kind == 'codex':
                    self.index_codex_databases(root)
                    for p in source_files(kind,root): self.index_file(p,'history' if p.name=='history.jsonl' else kind)
                elif kind == 'claude':
                    for p in source_files(kind,root): self.index_file(p,kind)
                elif kind == 'cursor':
                    for p in source_files(kind,root):
                        from viewer import records
                        self.put(kind,hashlib.sha256(str(p).encode()).hexdigest(),{},
                                 (block(r.get('message',{}).get('content',''),r.get('role','assistant')) for r in records(p,self.status['warnings'])))
                elif kind == 'grok': self.index_grok(root)
                elif kind == 'opencode': self.index_opencode(root)
                elif kind in ('claude_ai','chatgpt'): self.index_cloud(root,kind)
                else: self.status['warnings'].append(KINDS[kind]+': found, not yet supported')
            except Exception as e:
                self.status['warnings'].append(KINDS[kind]+': '+str(e))

    def index_codex_databases(self, root):
        meta = {}; parents = {}; ns = hashlib.sha256(str(root).encode()).hexdigest()[:12]+':'
        for db in sorted(root.glob('state_*.sqlite'), key=version):
            with database(db,self.cache) as c:
                ts=tables(c)
                if 'threads' not in ts: raise ValueError('Unknown Codex state schema')
                if 'threads' in ts:
                    for r in c.execute('SELECT * FROM threads'):
                        d=dict(r);meta[d['id']]=dict(title=d.get('title',''),project=d.get('cwd',''),start=millis(d['created_at_ms']) if d.get('created_at_ms') else __import__('viewer').stamp(d.get('created_at')),end=millis(d['updated_at_ms']) if d.get('updated_at_ms') else __import__('viewer').stamp(d.get('updated_at')),model=d.get('model') or d.get('model_provider') or '')
                        if d.get('attached_thread_parent_id'): parents[d['id']]=d['attached_thread_parent_id']
                if 'thread_spawn_edges' in ts: parents.update((r['child_thread_id'],r['parent_thread_id']) for r in c.execute('SELECT * FROM thread_spawn_edges'))
        # Later version files take precedence per thread; realtime and turn items merge by item ID.
        locations = {}
        for db in sorted(root.glob('thread_history_*.sqlite'), key=version):
            with database(db,self.cache) as c:
                if not tables(c) & {'thread_items','thread_realtime_items','thread_turns'}: raise ValueError('Unknown Codex history schema')
                for table in ('thread_turns','thread_items','thread_realtime_items'):
                    if table in tables(c):
                        for r in c.execute('SELECT DISTINCT thread_id FROM '+table): locations[r[0]]=db
        for db in set(locations.values()):
            with database(db,self.cache) as c:
                for tid in (tid for tid, location in locations.items() if location == db):
                    rows={}
                    for table in ('thread_items','thread_realtime_items'):
                        if table in tables(c):
                            for r in c.execute('SELECT * FROM '+table+' WHERE thread_id=?',(tid,)): rows[r['item_id']]=dict(r)
                    if not rows: continue # turn metadata alone is not a transcript; keep rollout fallback
                    self.primary_codex.add(tid)
                    def blocks():
                        for r in sorted(rows.values(),key=lambda r:(r['rollout_ordinal'],r['created_at_ms'])):
                            d=json.loads(r['item_json']);typ=d.get('type');at=millis(r['created_at_ms'])
                            if typ=='userMessage': yield block(d.get('content',[]),'user',at)
                            elif typ=='agentMessage': yield block(d.get('text',''),'assistant',at)
                            else: yield block(d,'tool',at,tool=True)
                    m=meta.get(tid,{}).copy();m['parent']='codex:'+ns+parents[tid] if tid in parents else ''
                    self.put('codex',tid,m,blocks(),ns)

    def index_grok(self, root):
        from viewer import records, stamp
        for path in source_files('grok',root):
            summary=path.parent/'summary.json'
            data=json.loads(summary.read_text(encoding='utf-8')) if summary.exists() else {}
            info=data.get('info') or {}
            def blocks():
                for r in records(path,self.status['warnings']):
                    typ=r.get('type','');at=stamp(r.get('timestamp') or data.get('created_at'))
                    if typ=='reasoning':
                        if r.get('summary'):yield block(r['summary'],'assistant',at,tool=True)
                    elif typ in ('tool_result','backend_tool_call'):
                        yield block(r.get('content',r),'tool',at,tool=True)
                    elif typ in ('system','user','assistant'):
                        yield block(r.get('content',''),typ,at,r.get('model_id',''))
                        if r.get('tool_calls'):yield block(r['tool_calls'],'tool',at,tool=True)
            self.put('grok',hashlib.sha256(str(path).encode()).hexdigest(),dict(title=data.get('generated_title') or '',project=info.get('cwd') or '',start=stamp(data.get('created_at')),end=stamp(data.get('updated_at')),model=data.get('current_model_id') or ''),blocks())

    def index_opencode(self, root):
        ns=hashlib.sha256(str(root).encode()).hexdigest()[:12]+':'
        if not (root/'opencode.db').exists():
            self.index_opencode_storage(root,ns,set()); return
        with database(root/'opencode.db',self.cache) as c:
            ts=tables(c);seen=set()
            for table in ('session_v2','session'):
                if table not in ts: continue
                for row in c.execute('SELECT * FROM '+table):
                    s=dict(row);sid=s['id']
                    if sid in seen:continue
                    seen.add(sid)
                    def blocks():
                        mt,pt=('session_message','session_part') if table=='session_v2' else ('message','part')
                        if mt not in ts:return
                        for r in c.execute('SELECT * FROM '+mt+' WHERE session_id=? ORDER BY time_created,id',(sid,)):
                            d=json.loads(r['data']);role=d.get('role') or (r['type'] if table=='session_v2' else 'assistant');at=millis(r['time_created'])
                            parts=[]
                            if pt in ts:
                                order='ordinal' if pt=='session_part' else 'time_created,id'
                                parts=[json.loads(p['data']) for p in c.execute('SELECT * FROM '+pt+' WHERE message_id=? ORDER BY '+order,(r['id'],))]
                            if not parts:
                                content=d.get('content')
                                parts=content if isinstance(content,list) else [{'type':'text','text':d.get('text',content or '')}]
                            for part in parts:
                                yield block(part.get('text',part),role,at,tool=part.get('type') not in ('text','reasoning'))
                    self.put('opencode',sid,dict(title=s['title'],project=s['directory'],start=millis(s['time_created']),end=millis(s['time_updated']),model=s.get('model') or '',parent='opencode:'+ns+s['parent_id'] if s.get('parent_id') else ''),blocks(),ns)
        self.index_opencode_storage(root,ns,seen)

    def index_opencode_storage(self, root, ns, seen):
        storage=root/'storage' if (root/'storage').exists() else root
        for path in (storage/'session').rglob('*.json'):
            s=json.loads(path.read_text(encoding='utf-8'));sid=s['id']
            if sid in seen:continue
            def blocks():
                messages=[json.loads(p.read_text(encoding='utf-8')) for p in (storage/'message'/sid).glob('*.json')]
                for m in sorted(messages,key=lambda m:(m.get('time',{}).get('created',0),m['id'])):
                    at=millis(m.get('time',{}).get('created'));role=m.get('role','assistant')
                    for path in sorted((storage/'part'/m['id']).glob('*.json')):
                        part=json.loads(path.read_text(encoding='utf-8'))
                        yield block(part.get('text',part),role,at,tool=part.get('type') not in ('text','reasoning'))
            time=s.get('time',{})
            self.put('opencode',sid,dict(title=s.get('title',''),project=s.get('directory',''),start=millis(time.get('created')),end=millis(time.get('updated')),parent='opencode:'+ns+s['parentID'] if s.get('parentID') else ''),blocks(),ns)


    def import_export(self, path, kind):
        if kind not in ('claude_ai','chatgpt'): raise ValueError('Unknown export format')
        with zipfile.ZipFile(Path(path).expanduser()) as z:
            members=[x for x in z.infolist() if Path(x.filename).name=='conversations.json']
            if len(members)!=1: raise ValueError('Expected exactly one conversations.json')
            if members[0].file_size>512*1024*1024: raise ValueError('Export exceeds 512 MB JSON limit')
            data=json.loads(z.read(members[0]))
        if not isinstance(data,list): raise ValueError('Expected a conversation list')
        for d in data:
            if not isinstance(d,dict) or ('chat_messages' not in d if kind=='claude_ai' else 'mapping' not in d): raise ValueError('Export does not match selected format')
        dest=self.cache/'imports';dest.mkdir(exist_ok=True)
        digest=hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()
        target=dest/(kind+'-'+digest+'.json');target.write_text(json.dumps(data),encoding='utf-8')
        if not any(s['path']==str(target) for s in self.config['sources']):
            self.config['sources'].append(dict(id=str(uuid.uuid4()),kind=kind,path=str(target),enabled=True))
        (self.cache/'config.json').write_text(json.dumps(self.config,indent=2),encoding='utf-8')

    def index_cloud(self, path, kind):
        from viewer import stamp
        for conversation in json.loads(path.read_text(encoding='utf-8')):
            cid=conversation.get('uuid') or conversation.get('id') or hashlib.sha256(json.dumps(conversation,sort_keys=True).encode()).hexdigest()
            def blocks():
                if kind=='claude_ai':
                    for m in conversation.get('chat_messages',[]):
                        content=m.get('content') or m.get('text','')
                        for part in content if isinstance(content,list) else [content]:
                            tool=isinstance(part,dict) and part.get('type') in ('tool_use','tool_result')
                            yield block(part,'user' if m.get('sender')=='human' else 'assistant',stamp(m.get('created_at')),tool=tool)
                else:
                    # Preserve all export branches once; do not silently discard alternate answers.
                    nodes=conversation.get('mapping',{})
                    msgs=[n.get('message') for n in nodes.values() if n.get('message')]
                    for m in sorted(msgs,key=lambda m:m.get('create_time') or 0):
                        content=m.get('content',{});role=m.get('author',{}).get('role','assistant')
                        yield block(content.get('parts',content),role,stamp(m.get('create_time')),m.get('metadata',{}).get('model_slug',''),role=='tool')
            self.put(kind,cid,dict(title=conversation.get('name') or conversation.get('title') or '',start=stamp(conversation.get('created_at',conversation.get('create_time')))),blocks())
