#!/usr/bin/env python3
"""Local, read-only session archive. No third-party Python packages."""
import argparse
import contextlib
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import threading
import tempfile
import time
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

APP = Path(__file__).resolve().parent
PREFIX = 'orchestration_v2_'
VERSION = '4'


def stamp(value):
    if isinstance(value, (int, float)):
        return dt.datetime.fromtimestamp(value, dt.timezone.utc).isoformat().replace('+00:00', 'Z')
    return str(value or '')


def without_images(value):
    if isinstance(value, list):
        return [without_images(v) for v in value]
    if isinstance(value, dict):
        if value.get('type') in ('image', 'input_image', 'output_image', 'image_url', 'base64'):
            return '[Image attachment omitted]'
        return {k: ('[Image attachment omitted]' if k == 'image_url' or (isinstance(v, str) and v.startswith('data:image/')) else without_images(v)) for k,v in value.items()}
    return value


def text_content(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return '\n'.join(text_content(v) for v in value)
    if isinstance(value, dict):
        if value.get('type') in ('text', 'input_text', 'output_text'):
            return value.get('text', '')
        return json.dumps(without_images(value), ensure_ascii=False)
    return '' if value is None else str(value)


@contextlib.contextmanager
def lines(path):
    """Decompress via a streaming subprocess; never rewrite a source file."""
    if path.name.endswith('.zst'):
        try:
            try:
                from compression import zstd as zstandard
            except ImportError:
                import zstandard
            with path.open('rb') as raw:
                if hasattr(zstandard.ZstdDecompressor, 'stream_reader'):
                    import io
                    with zstandard.ZstdDecompressor().stream_reader(raw) as stream:
                        with io.TextIOWrapper(stream, encoding='utf-8', errors='replace') as decoded:
                            yield decoded
                else:
                    with zstandard.open(raw, 'rt', encoding='utf-8', errors='replace') as decoded:
                        yield decoded
            return
        except ImportError:
            pass
        if not shutil.which('zstd'):
            raise RuntimeError('Compressed archives need Python 3.14+, optional zstandard package, or zstd executable. See README.')
        proc = subprocess.Popen(['zstd', '-dc', '--', str(path)], stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, text=True, encoding='utf-8', errors='replace')
        try:
            yield proc.stdout
            if proc.wait() != 0:
                raise RuntimeError('zstd decompression failed')
        finally:
            proc.stdout.close()
            if proc.poll() is None:
                proc.terminate()
            proc.wait()
    else:
        with path.open(encoding='utf-8', errors='replace') as f:
            yield f


def records(path, warnings):
    if path.suffix == '.json':
        with path.open(encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict):
            yield {'type': 'session_meta', 'payload': data.get('session', data)}
            yield from data.get('messages', data.get('items', []))
        elif isinstance(data, list):
            yield from data
        return
    with lines(path) as f:
        for number, line in enumerate(f, 1):
            try:
                record = json.loads(line)
                if isinstance(record, dict):
                    yield record
            except (ValueError, TypeError):
                warnings.append(f'{path.name}: invalid or unfinished record {number}') if len(warnings) < 100 else None


def parse(path, source, warnings):
    """Yield metadata patches and normalized blocks, one source record at a time."""
    model = ''
    session_at = ''
    seen = set()
    for d in records(path, warnings):
        p = d.get('payload') or {}
        typ = d.get('type', '')
        at = stamp(d.get('timestamp', d.get('ts'))) or session_at
        meta = {}
        if source == 'history':
            yield {'project': 'Typed prompt history', 'native_id': d.get('session_id', '')}, {
                'role': 'user', 'kind': 'message', 'time': at, 'model': '', 'text': d.get('text', '')}
            continue
        if source == 'claude':
            meta = {'project': d.get('cwd'), 'native_id': d.get('sessionId')}
            m = d.get('message') or {}
            model = m.get('model') or model
            if typ == 'summary':
                meta['title'] = d.get('summary')
            if typ not in ('user', 'assistant'):
                yield meta, None
                continue
            uid = d.get('uuid')
            if uid and uid in seen:
                continue
            if uid:
                seen.add(uid)
            content = m.get('content', '')
            for b in content if isinstance(content, list) else [content]:
                tool = isinstance(b, dict) and b.get('type') in ('tool_use', 'tool_result')
                yield meta, {'role': 'tool' if tool else typ, 'kind': 'tool' if tool else 'message',
                             'time': at, 'model': model, 'text': text_content(b)}
        else:
            if typ == 'session_meta':
                session_at = stamp(p.get('timestamp')) or at
                meta = {'project': p.get('cwd'), 'native_id': p.get('id', p.get('session_id')), 'start': session_at}
            if typ == 'turn_context':
                model = p.get('model') or model
                meta['model'] = model
            yield meta, None
            # event_msg duplicates response_item messages in current rollouts.
            if typ == 'event_msg':
                continue
            m = p if typ == 'response_item' else d
            mt = m.get('type', '')
            role = m.get('role')
            if mt == 'message' or (role in ('user', 'assistant') and 'content' in m):
                if role in ('user', 'assistant'):
                    yield {}, {'role': role, 'kind': 'message', 'time': at, 'model': model,
                               'text': text_content(m.get('content', ''))}
            elif mt in ('function_call', 'function_call_output', 'custom_tool_call', 'custom_tool_call_output', 'web_search_call', 'local_shell_call'):
                yield {}, {'role': 'tool', 'kind': 'tool', 'time': at, 'model': model, 'text': text_content(m)}


def signature(path):
    try:
        s = path.stat()
        return [s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns]
    except FileNotFoundError:
        return None


def snapshot(source, cache):
    """Copy a quiescent DB+WAL pair without opening/locking the live database."""
    key = hashlib.sha256(str(source).encode()).hexdigest()[:16]
    target = cache / (key + '.sqlite')
    marker = cache / (key + '.json')
    sources = [source, Path(str(source) + '-wal')]
    before = [signature(p) for p in sources]
    if marker.exists() and target.exists() and json.loads(marker.read_text()) == [str(source), before]:
        return target
    for attempt in range(5):
        staging = Path(tempfile.mkdtemp(prefix='snapshot-', dir=cache))
        dest = staging / 't3.sqlite'
        before = [signature(p) for p in sources]
        for src, dst in zip(sources, [dest, Path(str(dest) + '-wal')]):
            if src.exists():
                # APFS clone is fast and consumes only changed blocks.
                result = subprocess.run(['cp', '-c', str(src), str(dst)], capture_output=True) if sys.platform == 'darwin' else None
                if result is None or result.returncode:
                    shutil.copyfile(src, dst)
        after = [signature(p) for p in sources]
        if before == after and before[0]:
            # Open only the copy. Recover WAL in cache, then detach it for immutable reads.
            with sqlite3.connect(dest, factory=ClosingConnection) as c:
                c.execute('PRAGMA wal_checkpoint(TRUNCATE)')
                c.execute('PRAGMA journal_mode=DELETE')
            os.replace(dest, target)
            marker.write_text(json.dumps([str(source), after]))
            shutil.rmtree(staging)
            return target
        shutil.rmtree(staging)
    raise RuntimeError('Database kept changing during snapshot; retry refresh. Existing index remains available.')


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


from sources import SourceMethods


class Store(SourceMethods):
    def __init__(self, args):
        self.args = args
        self.cache = Path(args.data_dir)
        if APP == self.cache.resolve() or APP in self.cache.resolve().parents:
            raise ValueError('App data must live outside the repository')
        if self.cache.is_symlink():
            raise ValueError('The app cache must be a local folder, not a symlink')
        from sources import load_config
        self.cache.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.config = load_config(self.cache)
        args.t3 = next((x['path'] for x in self.config['sources'] if x['kind'] == 't3'), '')
        args.claude = args.codex = ''
        for source in (x['path'] for x in self.config['sources']):
            path = Path(source).expanduser().resolve()
            if (path == self.cache.resolve() or self.cache.resolve() in path.parents) and path.parent != (self.cache/'imports').resolve():
                raise ValueError('Source paths must be outside the app cache')
        self.cache.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.db = self.cache / 'index.sqlite'
        self.status = {'busy': False, 'phase': 'Ready', 'warnings': [], 'indexed_files': 0}
        self.lock = threading.Lock()
        self.tag_dirty = set()
        self.primary_codex = set()
        with self.connect() as c:
            c.executescript('''
            DROP TRIGGER IF EXISTS bi;
            DROP TRIGGER IF EXISTS bd;
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, source TEXT, title TEXT,
              project TEXT, start TEXT, end TEXT, count INTEGER, model TEXT, parent TEXT, native_id TEXT);
            CREATE INDEX IF NOT EXISTS sessions_date ON sessions(start DESC);
            CREATE TABLE IF NOT EXISTS blocks(id INTEGER PRIMARY KEY, session TEXT, role TEXT,
              kind TEXT, time TEXT, model TEXT, text TEXT);
            CREATE INDEX IF NOT EXISTS blocks_session ON blocks(session,id);
            CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(text, content='blocks',content_rowid='id');
            CREATE TRIGGER IF NOT EXISTS bi AFTER INSERT ON blocks BEGIN
              INSERT INTO search(rowid,text) VALUES(new.id,unpack(new.text)); END;
            CREATE TRIGGER IF NOT EXISTS bd AFTER DELETE ON blocks BEGIN
              INSERT INTO search(search,rowid,text) VALUES('delete',old.id,unpack(old.text)); END;
            CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, signature TEXT, session TEXT);
            CREATE TABLE IF NOT EXISTS tags(session TEXT, tag TEXT, PRIMARY KEY(session,tag));
            ''')

    def connect(self):
        c = sqlite3.connect(self.db, timeout=10, factory=ClosingConnection)
        c.create_function('unpack', 1, lambda x: zlib.decompress(x).decode('utf-8') if isinstance(x, bytes) else x)
        def row(cursor, values):
            return sqlite3.Row(cursor, tuple(zlib.decompress(v).decode('utf-8') if isinstance(v, bytes) and cursor.description[i][0] == 'text' else v for i,v in enumerate(values)))
        c.row_factory = row
        return c

    def start(self):
        if not self.lock.acquire(blocking=False):
            return
        self.status.update(busy=True, phase='Starting', warnings=[], indexed_files=0)
        threading.Thread(target=self.refresh, daemon=True).start()

    def add_block(self, c, sid, b):
        if b and b.get('text'):
            c.execute('INSERT INTO blocks(session,role,kind,time,model,text) VALUES(?,?,?,?,?,?)',
                      (sid, b['role'], b['kind'], b['time'], b['model'], zlib.compress(b['text'].encode(), 1) if len(b['text']) > 512 else b['text']))

    def refresh(self):
        start = time.monotonic()
        self.tag_dirty.clear()
        try:
            self.refresh_sources()
            self.status['phase'] = 'Applying tag names'
            rules = self.config['tags']
            names = list(rules)
            with self.connect() as c:
                tag_marker = self.cache / 'tags-indexed.json'
                all_tags = not tag_marker.exists() or json.loads(tag_marker.read_text()) != rules
                import re
                patterns = [(name, [re.compile(r'(?<!\w)' + re.escape(k).replace(r'\ ', r'\s+') + r'(?!\w)', re.I) for k in keywords]) for name, keywords in rules.items()]
                for row in c.execute('SELECT id,title,project FROM sessions').fetchall():
                    sid = row['id']
                    if not all_tags and sid not in self.tag_dirty:
                        continue
                    c.execute('DELETE FROM tags WHERE session=?', (sid,))
                    pending = dict(patterns)
                    texts = [row['title'] + ' ' + row['project']]
                    def apply(text):
                        for name, patterns in list(pending.items()):
                            if any(p.search(text) for p in patterns):
                                c.execute('INSERT OR IGNORE INTO tags VALUES(?,?)', (sid, name))
                                del pending[name]
                    apply(texts[0])
                    if pending:
                        for block in c.execute('SELECT text FROM blocks WHERE session=?', (sid,)):
                            apply(block['text'])
                            if not pending: break
            tag_marker.write_text(json.dumps(rules))
            self.status['phase'] = 'Ready'
        except Exception as e:
            self.status['phase'] = 'Refresh stopped: ' + str(e)
        finally:
            self.status.update(busy=False, seconds=round(time.monotonic() - start, 3))
            self.lock.release()

    @staticmethod
    def codex_paths(root):
        for name in ('sessions', 'archived_sessions'):
            folder = root / name
            if folder.exists():
                for p in folder.rglob('*'):
                    if p.is_file() and (p.suffix in ('.json', '.jsonl') or p.name.endswith('.jsonl.zst')):
                        yield p
        if (root / 'history.jsonl').exists():
            yield root / 'history.jsonl'

    def index_file(self, path, source):
        sig = json.dumps([VERSION + '-legacy2' if path.suffix == '.json' else VERSION, signature(path)])
        sid = source + ':' + hashlib.sha256(str(path).encode()).hexdigest()[:24]
        with self.connect() as c:
            old = c.execute('SELECT signature FROM files WHERE path=?', (str(path),)).fetchone()
            if old and old[0] == sig:
                return
            try:
                c.execute('DELETE FROM blocks WHERE session=?', (sid,))
                meta = dict(id=sid, source=source, title='', project=str(path.parent), start='', end='', count=0, model='', parent='', native_id='')
                for patch, block in parse(path, source, self.status['warnings']):
                    meta.update({k: v for k, v in patch.items() if v})
                    if source == 'codex' and meta['native_id'] in self.primary_codex:
                        c.execute('DELETE FROM sessions WHERE id=?', (sid,))
                        c.execute('DELETE FROM files WHERE path=?', (str(path),))
                        return
                    if block and block['text']:
                        if not meta['title'] and block['role'] == 'user':
                            meta['title'] = block['text'].strip()[:180]
                        meta['start'] = min(meta['start'] or block['time'], block['time']) if block['time'] else meta['start']
                        meta['end'] = max(meta['end'], block['time'])
                        meta['model'] = block['model'] or meta['model']
                        meta['count'] += block['kind'] == 'message'
                        self.add_block(c, sid, block)
                if source == 'codex' and meta['native_id'] in getattr(self, 'primary_codex', set()):
                    c.execute('DELETE FROM sessions WHERE id=?', (sid,))
                    c.execute('DELETE FROM blocks WHERE session=?', (sid,))
                    return
                meta['title'] = meta['title'] or path.name
                if source == 'history':
                    meta['title'] = 'Codex typed prompt history'
                c.execute('INSERT OR REPLACE INTO sessions VALUES(:id,:source,:title,:project,:start,:end,:count,:model,:parent,:native_id)', meta)
                c.execute('INSERT OR REPLACE INTO files VALUES(?,?,?)', (str(path), sig, sid))
                self.tag_dirty.add(sid)
                self.status['indexed_files'] += 1
            except Exception as e:
                c.rollback()
                self.status['warnings'].append(path.name + ': ' + str(e))

    def index_t3(self, path):
        src = sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True)
        src.row_factory = sqlite3.Row
        try:
            self.status['phase'] = 'Listing T3 threads'
            with self.connect() as c:
                projects = {r['project_id']: r['workspace_root'] for r in src.execute('SELECT * FROM projection_projects')}
                counts = dict(src.execute('SELECT thread_id,count(*) FROM '+PREFIX+'projection_messages GROUP BY thread_id'))
                threads = src.execute('SELECT * FROM '+PREFIX+'projection_threads').fetchall()
                for s in threads:
                    p = json.loads(s['payload_json']);sid = 't3:' + hashlib.sha256(str(self.args.t3).encode()).hexdigest()[:12] + ':' + s['thread_id']
                    parent = (p.get('lineage') or {}).get('parentThreadId') or ''
                    model = (p.get('modelSelection') or {}).get('model') or s['default_provider']
                    c.execute('INSERT OR REPLACE INTO sessions VALUES(?,?,?,?,?,?,?,?,?,?)',
                              (sid, 't3', s['title'], p.get('worktreePath') or projects.get(s['project_id'], s['project_id']),
                               s['created_at'], s['updated_at'], counts.get(s['thread_id'], 0), model,
                               't3:' + hashlib.sha256(str(self.args.t3).encode()).hexdigest()[:12] + ':' + parent if parent else '', s['thread_id']))
            self.status['phase'] = 'Indexing T3 transcripts'
            for s in threads:
                sid = 't3:' + hashlib.sha256(str(self.args.t3).encode()).hexdigest()[:12] + ':' + s['thread_id']; key = 't3-thread:' + str(self.args.t3) + ':' + s['thread_id']
                sig = json.dumps([VERSION, s['updated_at'], counts.get(s['thread_id'], 0)])
                with self.connect() as c:
                    old = c.execute('SELECT signature FROM files WHERE path=?', (key,)).fetchone()
                    if old and old[0] == sig:
                        continue
                    self.tag_dirty.add(sid)
                    c.execute('DELETE FROM blocks WHERE session=?', (sid,))
                    for m in src.execute('SELECT * FROM '+PREFIX+'projection_messages WHERE thread_id=? ORDER BY created_at,message_id', (s['thread_id'],)):
                        p = json.loads(m['payload_json'])
                        self.add_block(c, sid, {'role': m['role'], 'kind': 'message', 'time': m['created_at'],
                                              'model': '', 'text': p.get('text', '')})
                    for item in src.execute('SELECT * FROM '+PREFIX+"projection_turn_items WHERE thread_id=? AND type NOT IN ('user_message','assistant_message') ORDER BY ordinal", (s['thread_id'],)):
                        p = json.loads(item['payload_json'])
                        self.add_block(c, sid, {'role': 'tool', 'kind': 'tool', 'time': p.get('startedAt') or item['updated_at'],
                                              'model': '', 'text': text_content(p)})
                    c.execute('INSERT OR REPLACE INTO files VALUES(?,?,?)', (key, sig, sid))
            # Probe native FTS. The cache index includes helper/tool text missing from it.
            try:
                src.execute('SELECT rowid FROM '+PREFIX+'message_search WHERE text MATCH ? LIMIT 1', ('"session"',)).fetchall()
                self.status['native_fts'] = True
            except sqlite3.Error:
                self.status['native_fts'] = False
        finally:
            src.close()

    def listing(self, q):
        where, params = [], []
        for field in ('source', 'project'):
            if q.get(field):
                where.append('s.'+field+'=?');params.append(q[field])
        if q.get('from'):
            where.append('s.start>=?');params.append(q['from'])
        if q.get('to'):
            where.append('substr(s.start,1,10)<=?');params.append(q['to'])
        if q.get('tag'):
            where.append('EXISTS(SELECT 1 FROM tags t WHERE t.session=s.id AND t.tag=?)');params.append(q['tag'])
        if q.get('q'):
            phrase = '"' + q['q'].replace('"', '""') + '"'
            where.append('s.id IN (SELECT b.session FROM search JOIN blocks b ON b.id=search.rowid WHERE search MATCH ?)')
            params.append(phrase)
        clause = ' WHERE ' + ' AND '.join(where) if where else ''
        page = max(0, int(q.get('page', 0)))
        order = 'ASC' if q.get('chain') == '1' else 'DESC'
        with self.connect() as c:
            total = c.execute('SELECT count(*) FROM sessions s'+clause, params).fetchone()[0]
            rows = c.execute('SELECT s.* FROM sessions s'+clause+' ORDER BY start '+order+',id LIMIT 50 OFFSET ?', params+[page*50]).fetchall()
            return {'sessions': [dict(r) for r in rows], 'total': total, 'page': page}

    def session(self, sid, page=0):
        with self.connect() as c:
            s = c.execute('SELECT * FROM sessions WHERE id=?', (sid,)).fetchone()
            if not s:
                raise ValueError('Session not found')
            relatives = c.execute('SELECT id,title FROM sessions WHERE id=? OR parent=? ORDER BY start', (s['parent'], sid)).fetchall()
            blocks = c.execute('SELECT * FROM blocks WHERE session=? ORDER BY time,id LIMIT 100 OFFSET ?', (sid,page*100)).fetchall()
            total = c.execute('SELECT count(*) FROM blocks WHERE session=?', (sid,)).fetchone()[0]
            return {'session': dict(s), 'relatives': [dict(r) for r in relatives], 'blocks': [dict(r) for r in blocks], 'total': total}

    def export(self, q):
        with self.connect() as c:
            if q.get('id'):
                sessions = c.execute('SELECT * FROM sessions WHERE id=?', (q['id'],)).fetchall()
            else:
                sessions = c.execute('SELECT s.* FROM sessions s JOIN tags t ON t.session=s.id WHERE t.tag=? ORDER BY s.start,s.id', (q.get('tag', ''),)).fetchall()
            for s in sessions:
                yield f"# {s['title']}\n\n{s['source']} · {s['project']}\n\n{s['start']} — {s['end']} · {s['model']}\n\n"
                for b in c.execute('SELECT * FROM blocks WHERE session=? ORDER BY time,id', (s['id'],)):
                    yield f"## {b['role']} · {b['time']} {b['model']}\n\n{b['text']}\n\n"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Do not log search terms or confidential session IDs.

    def do_GET(self):
        if self.headers.get('Host') not in ('127.0.0.1:'+str(self.server.server_port), 'localhost:'+str(self.server.server_port)):
            self.send_error(403);return
        parsed = urlparse(self.path)
        q = {k: v[0] for k,v in parse_qs(parsed.query).items()}
        try:
            if parsed.path == '/':
                self.send_data((APP/'static/index.html').read_bytes(), 'text/html; charset=utf-8');return
            if parsed.path == '/api/status':
                with self.server.store.connect() as c:
                    result = dict(self.server.store.status)
                    result['counts'] = dict(c.execute('SELECT source,count(*) FROM sessions GROUP BY source'))
                    result['projects'] = [r[0] for r in c.execute('SELECT DISTINCT project FROM sessions ORDER BY project')]
                    result['tags'] = list(self.server.store.config['tags'])
            elif parsed.path == '/api/sources':
                result = self.server.store.discovery()
            elif parsed.path in ('/static/style.css', '/static/app.js'):
                self.send_data((APP/parsed.path.lstrip('/')).read_bytes(), 'text/css' if parsed.path.endswith('.css') else 'text/javascript');return
            elif parsed.path == '/api/list':
                result = self.server.store.listing(q)
            elif parsed.path == '/api/session':
                result = self.server.store.session(q['id'], max(0,int(q.get('page',0))))
            elif parsed.path == '/export':
                self.send_response(200)
                self.headers_common('text/markdown; charset=utf-8')
                self.send_header('Content-Disposition', 'attachment; filename="sessions.md"')
                self.end_headers()
                for part in self.server.store.export(q):
                    self.wfile.write(part.encode())
                return
            else:
                self.send_error(404);return
            self.send_data(json.dumps(result).encode(), 'application/json')
        except (ValueError, KeyError) as e:
            self.send_data(json.dumps({'error':str(e)}).encode(), 'application/json',400)
        except Exception:
            self.send_data(b'{"error":"Local read failed. Check the refresh status and README."}', 'application/json',500)

    def do_POST(self):
        origin = 'http://127.0.0.1:' + str(self.server.server_port)
        if self.headers.get('Host') != origin[7:] or self.headers.get('Origin') != origin:
            self.send_error(403); return
        try:
            length = int(self.headers.get('Content-Length', 0))
            if length <= 0 or length > 65536: raise ValueError('Request too large')
            data = json.loads(self.rfile.read(length))
            if self.server.store.status['busy']: raise ValueError('Wait for refresh to finish')
            if self.path == '/api/config':
                self.server.store.save_config(data)
            elif self.path == '/api/import':
                self.server.store.import_export(data['path'], data['kind'])
            elif self.path != '/api/refresh':
                self.send_error(404); return
            self.server.store.start()
            self.send_data(b'{"ok":true}', 'application/json')
        except (ValueError, KeyError, OSError, __import__('zipfile').BadZipFile) as e:
            self.send_data(json.dumps({'error': str(e)}).encode(), 'application/json', 400)

    def headers_common(self, mime):
        self.send_header('Content-Type', mime)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")

    def send_data(self, data, mime, code=200):
        self.send_response(code);self.headers_common(mime)
        self.send_header('Content-Length', str(len(data)));self.end_headers();self.wfile.write(data)


def arguments():
    from sources import defaults, app_data
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data-dir', default=str(app_data()))
    p.add_argument('--port', type=int, default=8765)
    return p.parse_args()


if __name__ == '__main__':
    os.umask(0o077)
    args = arguments()
    store = Store(args)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    server.store = store
    print(f'LEJ AI Session Archive Viewer: http://127.0.0.1:{args.port} (Ctrl-C to stop)', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
