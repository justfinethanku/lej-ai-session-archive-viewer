import argparse
import hashlib
import json
from pathlib import Path, PureWindowsPath
import sqlite3
import tempfile
import unittest
import zipfile
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import viewer
import contextlib
from sources import defaults, app_data, database

@contextlib.contextmanager
def fixture_db(path):
    c=sqlite3.connect(path)
    try:
        with c: yield c
    finally:c.close()

class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.store=viewer.Store(argparse.Namespace(data_dir=str(self.root/'cache')))
    def tearDown(self): self.tmp.cleanup()
    def configure(self,kind,path,tags=None):
        self.store.save_config({'sources':[{'id':'sample','kind':kind,'path':str(path),'enabled':True}], 'tags':tags or {}})
    def refresh(self):
        self.store.lock.acquire();self.store.refresh()
        self.assertEqual(self.store.status['phase'],'Ready');self.assertFalse(self.store.status['warnings'])
    def test_windows_paths(self):
        env={'USERPROFILE':r'C:\Users\Sample','APPDATA':r'D:\Roaming','LOCALAPPDATA':r'D:\Local'}
        d=defaults('win32',env=env)
        paths={(x['kind'],x['path']) for x in d}
        self.assertIn(('claude',r'C:\Users\Sample\.claude'),paths)
        self.assertIn(('codex',r'C:\Users\Sample\.codex'),paths)
        self.assertIn(('cursor_app',r'D:\Roaming\Cursor'),paths)
        self.assertIn(('opencode',r'D:\Local\opencode'),paths)
        self.assertEqual(str(app_data('win32',r'C:\Users\Sample',env)),r'D:\Local\lej-ai-session-archive-viewer')
    def test_macos_linux_paths(self):
        self.assertEqual(defaults('darwin','/home/sample',{})[2]['path'],'/home/sample/.t3/userdata/statev2.sqlite')
        self.assertEqual(str(app_data('linux','/home/sample',{'XDG_DATA_HOME':'/data'})),'/data/lej-ai-session-archive-viewer')
    def test_claude_filters_tags_disable(self):
        root=self.root/'copied.claude';root.mkdir()
        (root/'chat.jsonl').write_text(json.dumps({'type':'user','sessionId':'s','timestamp':'2026-01-01T00:00:00Z','message':{'content':'Build a garden planner'}})+'\n'+json.dumps({'type':'assistant','timestamp':'2026-01-01T00:00:01Z','message':{'content':[{'type':'tool_use','name':'Read','input':{'file':'sample.txt'}}]}})+'\n')
        self.configure('claude',root,{'hobby':['garden']});self.refresh()
        rows=self.store.listing({'tag':'hobby','q':'garden'})
        self.assertEqual(rows['total'],1)
        sid=rows['sessions'][0]['id'];self.assertEqual(self.store.session(sid)['blocks'][1]['kind'],'tool')
        self.assertIn('garden',''.join(self.store.export({'tag':'hobby'})))
        config=self.store.config;config['sources'][0]['enabled']=False;self.store.save_config(config);self.refresh()
        self.assertEqual(self.store.listing({})['total'],0)
    def test_cursor(self):
        root=self.root/'cursor';root.mkdir();(root/'chat.jsonl').write_text(json.dumps({'role':'user','message':{'content':[{'type':'text','text':'Synthetic prompt'}]}})+'\n')
        self.configure('cursor',root);self.refresh();self.assertEqual(self.store.listing({'q':'Synthetic'})['total'],1)
    def test_codex_database_precedence_realtime_and_lineage(self):
        root=self.root/'codex';(root/'sessions').mkdir(parents=True)
        db=root/'thread_history_9.sqlite'
        with fixture_db(db) as c:
            c.execute('CREATE TABLE thread_items(thread_id,turn_id,item_id,rollout_ordinal,created_at_ms,item_json)')
            c.execute('CREATE TABLE thread_realtime_items(thread_id,item_id,rollout_ordinal,created_at_ms,item_json)')
            c.execute('CREATE TABLE thread_turns(thread_id)')
            c.execute('INSERT INTO thread_items VALUES(?,?,?,?,?,?)',('a','turn','one',1,1000,json.dumps({'type':'userMessage','content':[{'type':'text','text':'database primary'}]})))
            c.execute('INSERT INTO thread_realtime_items VALUES(?,?,?,?,?)',('a','two',2,2000,json.dumps({'type':'agentMessage','text':'Realtime reply'})))
        with fixture_db(root/'state_8.sqlite') as c:
            c.execute('CREATE TABLE threads(id,title,cwd,created_at,updated_at,model)')
            c.execute("INSERT INTO threads VALUES('a','Title','sample',1,2,'example-model')")
            c.execute('CREATE TABLE thread_spawn_edges(parent_thread_id,child_thread_id)')
            c.execute("INSERT INTO thread_spawn_edges VALUES('parent','a')")
        (root/'sessions/rollout.jsonl').write_text(json.dumps({'type':'session_meta','payload':{'id':'a'}})+'\n'+json.dumps({'type':'response_item','payload':{'type':'message','role':'user','content':'file duplicate'}})+'\n{')
        self.configure('codex',root);self.refresh()
        result=self.store.listing({});self.assertEqual(result['total'],1)
        session=self.store.session(result['sessions'][0]['id']);self.assertEqual(len(session['blocks']),2);self.assertTrue(session['session']['parent'].endswith('parent'))
        self.assertEqual(self.store.listing({'q':'duplicate'})['total'],0)
        self.assertEqual(self.store.discovery()['sources'][0]['count'],1)
    def test_legacy_and_history(self):
        root=self.root/'codex';(root/'archived_sessions').mkdir(parents=True)
        (root/'archived_sessions/legacy.json').write_text(json.dumps({'session':{'id':'legacy','timestamp':'2026-01-01'},'messages':[{'role':'user','content':'Legacy prompt'}]}))
        (root/'history.jsonl').write_text(json.dumps({'session_id':'legacy','ts':1,'text':'History prompt'})+'\n')
        self.configure('codex',root);self.refresh();self.assertEqual(self.store.listing({})['total'],2)
    def test_imports_branches_and_repeat(self):
        for kind,data in [('claude_ai',[{'uuid':'cloud-one','name':'Synthetic','chat_messages':[{'sender':'human','text':'Cloud garden'}]}]),('chatgpt',[{'id':'cloud-two','title':'Synthetic','mapping':{'a':{'message':{'author':{'role':'user'},'content':{'parts':['Cloud prompt']},'create_time':1}},'b':{'message':{'author':{'role':'assistant'},'content':{'parts':['Alternate reply']},'create_time':2}}}}])]:
            p=self.root/(kind+'.zip')
            with zipfile.ZipFile(p,'w') as z:z.writestr('export/conversations.json',json.dumps(data))
            self.store.import_export(str(p),kind);self.store.import_export(str(p),kind)
        self.store.save_config(self.store.config);self.refresh()
        self.assertEqual(self.store.listing({})['total'],2)
        self.assertEqual(self.store.listing({'q':'Alternate'})['total'],1)
    def test_invalid_zip(self):
        p=self.root/'bad.zip'
        with zipfile.ZipFile(p,'w') as z:z.writestr('../unrelated.json','[]')
        with self.assertRaises(ValueError):self.store.import_export(str(p),'claude_ai')
    def test_snapshot_wal_read_only(self):
        db=self.root/'source.sqlite';c=sqlite3.connect(db);c.execute('PRAGMA journal_mode=WAL');c.execute('CREATE TABLE sample(value)');c.execute("INSERT INTO sample VALUES('synthetic')");c.commit()
        before=[viewer.signature(p) for p in (db,Path(str(db)+'-wal'))]
        with database(db,self.store.cache) as copy:
            self.assertEqual(copy.execute('SELECT value FROM sample').fetchone()[0],'synthetic')
            with self.assertRaises(sqlite3.OperationalError):copy.execute('DELETE FROM sample')
        self.assertEqual(before,[viewer.signature(p) for p in (db,Path(str(db)+'-wal'))]);c.close()
    def test_source_collision(self):
        with self.assertRaises(ValueError):self.configure('claude',self.store.cache)
    def test_unknown_detected_not_supported(self):
        p=self.root/'gemini';p.mkdir();self.configure('gemini',p)
        s=self.store.discovery()['sources'][0];self.assertFalse(s['supported']);self.assertEqual(s['status'],'Found, not yet supported');self.assertIsNone(s['count'])
    def test_pagination_search_export(self):
        self.store.put('sample','one',{},({'text':'Synthetic '+str(i),'role':'user','kind':'message','time':str(i).zfill(4),'model':''} for i in range(111)))
        self.assertEqual(len(self.store.session('sample:one',1)['blocks']),11)
        self.assertEqual(self.store.listing({'q':'Synthetic'})['total'],1)
        self.assertIn('Synthetic 110',''.join(self.store.export({'id':'sample:one'})))

    def test_unrecognized_codex_database(self):
        root=self.root/'codex';root.mkdir()
        with fixture_db(root/'thread_history_22.sqlite') as c:c.execute('CREATE TABLE unknown(value)')
        self.configure('codex',root)
        source=self.store.discovery()['sources'][0]
        self.assertFalse(source['supported']);self.assertIn('not yet supported',source['status'])

    def test_grok_chat_history(self):
        root=self.root/'grok/sessions/example';root.mkdir(parents=True)
        (root/'chat_history.jsonl').write_text('\n'.join(json.dumps(r) for r in [{'type':'user','content':[{'type':'text','text':'Synthetic grok'}]},{'type':'assistant','content':'Reply','tool_calls':[{'name':'example'}]},{'type':'tool_result','content':'Example result'}])+'\n')
        self.configure('grok',self.root/'grok');self.refresh()
        row=self.store.listing({'q':'Synthetic'})['sessions'][0]
        self.assertEqual(sum(b['kind']=='tool' for b in self.store.session(row['id'])['blocks']),2)

    def test_opencode_both_schemas(self):
        root=self.root/'opencode';root.mkdir()
        with fixture_db(root/'opencode.db') as c:
            for t in ('session','session_v2'):
                c.execute('CREATE TABLE '+t+'(id,title,directory,time_created,time_updated,parent_id,model)')
            c.execute("INSERT INTO session VALUES('old','Old','project',1000,2000,NULL,NULL)")
            c.execute("INSERT INTO session_v2 VALUES('new','New','project',2000,3000,'old',NULL)")
            c.execute('CREATE TABLE message(id,session_id,time_created,data)')
            c.execute('CREATE TABLE part(id,message_id,time_created,data)')
            c.execute('CREATE TABLE session_message(id,session_id,time_created,type,data)')
            c.execute('INSERT INTO message VALUES(?,?,?,?)',('m','old',1000,json.dumps({'role':'user'})))
            c.execute('INSERT INTO part VALUES(?,?,?,?)',('p','m',1000,json.dumps({'type':'text','text':'Legacy garden'})))
            c.execute('INSERT INTO session_message VALUES(?,?,?,?,?)',('n','new',2000,'assistant',json.dumps({'content':[{'type':'text','text':'New garden reply'},{'type':'tool','name':'example','state':{'output':'Synthetic result'}}]})))
        self.configure('opencode',root);self.refresh()
        self.assertEqual(self.store.listing({'q':'garden'})['total'],2)
        child=next(x for x in self.store.listing({})['sessions'] if x['title']=='New')
        self.assertEqual(len(self.store.session(child['id'])['relatives']),1)
        self.assertEqual(self.store.session(child['id'])['blocks'][-1]['kind'],'tool')
    def test_opencode_legacy_storage(self):
        root=self.root/'opencode/storage'
        for path,data in [('session/project/s.json',{'id':'s','title':'Legacy','directory':'sample','time':{'created':1000}}),('message/s/m.json',{'id':'m','role':'user','time':{'created':1000}}),('part/m/p.json',{'type':'text','text':'Legacy storage prompt'})]:
            f=root/path;f.parent.mkdir(parents=True,exist_ok=True);f.write_text(json.dumps(data))
        self.configure('opencode',root.parent);self.refresh()
        self.assertEqual(self.store.listing({'q':'Legacy storage'})['total'],1)
        self.assertEqual(self.store.discovery()['sources'][0]['count'],1)

    def test_t3_tools_and_lineage(self):
        db=self.root/'t3.sqlite'
        with fixture_db(db) as c:
            c.execute('CREATE TABLE projection_projects(project_id,workspace_root)')
            c.execute("INSERT INTO projection_projects VALUES('p','synthetic')")
            c.execute('CREATE TABLE orchestration_v2_projection_threads(thread_id,project_id,title,default_provider,created_at,updated_at,payload_json)')
            c.execute('CREATE TABLE orchestration_v2_projection_messages(thread_id,message_id,role,created_at,payload_json)')
            c.execute('CREATE TABLE orchestration_v2_projection_turn_items(thread_id,type,ordinal,updated_at,payload_json)')
            for sid,parent in [('parent',''),('child','parent')]:
                c.execute('INSERT INTO orchestration_v2_projection_threads VALUES(?,?,?,?,?,?,?)',(sid,'p',sid,'sample','2026-01-01','2026-01-02',json.dumps({'lineage':{'parentThreadId':parent}})))
                c.execute('INSERT INTO orchestration_v2_projection_messages VALUES(?,?,?,?,?)',(sid,sid,'user','2026-01-01',json.dumps({'text':'Synthetic T3 prompt'})))
            c.execute('INSERT INTO orchestration_v2_projection_turn_items VALUES(?,?,?,?,?)',('child','tool',0,'2026-01-02',json.dumps({'text':'Tool detail'})))
        self.configure('t3',db);self.refresh()
        rows=self.store.listing({})['sessions'];self.assertEqual(len(rows),2)
        child=next(r for r in rows if r['title']=='child');result=self.store.session(child['id'])
        self.assertEqual(len(result['relatives']),1);self.assertEqual(result['blocks'][-1]['kind'],'tool')
    def test_zstd_and_partial_jsonl(self):
        import shutil,subprocess
        try:
            from compression import zstd
        except ImportError:
            zstd=None
        if zstd is None and not shutil.which('zstd'):self.skipTest('optional zstd decoder absent')
        root=self.root/'codex';(root/'archived_sessions').mkdir(parents=True)
        raw=json.dumps({'type':'response_item','payload':{'type':'message','role':'user','content':'Compressed synthetic'}}).encode()+b'\n'
        zipped=zstd.compress(raw) if zstd else subprocess.run(['zstd','-c'],input=raw,capture_output=True,check=True).stdout
        (root/'archived_sessions/sample.jsonl.zst').write_bytes(zipped)
        self.configure('codex',root);self.refresh();self.assertEqual(self.store.listing({'q':'Compressed'})['total'],1)
        p=self.root/'partial.jsonl';p.write_text(raw.decode()+'{')
        warnings=[];self.assertEqual(len(list(viewer.records(p,warnings))),1);self.assertEqual(len(warnings),1)
    def test_http_security_and_routes(self):
        import threading,urllib.request,urllib.error
        server=viewer.ThreadingHTTPServer(('127.0.0.1',0),viewer.Handler);server.store=self.store
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base='http://127.0.0.1:'+str(server.server_port)
        try:
            for path in ('/','/static/app.js','/static/style.css','/api/status','/api/list','/api/sources'):
                with urllib.request.urlopen(base+path) as r:self.assertEqual(r.status,200)
            for headers in ({'Host':'foreign.invalid'},{'Host':'foreign.invalid','Origin':'http://foreign.invalid'}):
                req=urllib.request.Request(base+'/api/config',data=b'{}',headers=headers,method='POST')
                with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(req)
                self.assertEqual(error.exception.code,403);error.exception.close()
            req=urllib.request.Request(base+'/api/config',data=json.dumps({'sources':[],'tags':{}}).encode(),headers={'Origin':base,'Content-Type':'application/json'},method='POST')
            with urllib.request.urlopen(req) as r:self.assertEqual(r.status,200)
            while self.store.status['busy']:threading.Event().wait(0.01)
        finally:server.shutdown();server.server_close();thread.join()
    def test_repo_cache_rejected(self):
        with self.assertRaises(ValueError):viewer.Store(argparse.Namespace(data_dir=str(viewer.APP/'cache')))

if __name__=='__main__':unittest.main()
