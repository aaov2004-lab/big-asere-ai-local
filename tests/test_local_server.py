import json
import os
import re
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

import requests

SCRIPT = Path(__file__).resolve().parents[1] / 'BigAsereAI' / 'Resources' / 'server.py'


class OllamaMock(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({'models': [{'name': 'qwen2.5-coder:7b'}, {'name': 'test:latest'}]}).encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        assert payload['model'] in ('test:latest', 'qwen2.5-coder:7b')
        assert payload['messages'][-1]['role'] == 'user'
        assert 'MODO ACTUAL:' in payload['messages'][0]['content']
        self.send_response(200)
        self.send_header('Content-Type', 'application/x-ndjson')
        self.end_headers()
        for msg in [{'message': {'content': 'Hola'}}, {'message': {'content': ' desde Ollama'}}, {'done': True, 'message': {'content': ''}}]:
            self.wfile.write(json.dumps(msg).encode() + b'\n')
            self.wfile.flush()

    def log_message(self, *args):
        pass


def test_app_api_and_security():
    with TemporaryDirectory() as tmp:
        project = Path(tmp) / 'repo'
        project.mkdir()
        (project / 'hello.py').write_text('print("Hola Big Asere")\n')
        (project / '.env').write_text('SECRET=123\n')
        (project / 'credentials.json').write_text('{"key":"secret"}')
        (project / 'notes.md').write_text('# Notas para la IA\n')
        (Path(tmp) / 'outside.py').write_text('TOP SECRET')
        data_dir = Path(tmp) / 'appdata'
        data_dir.mkdir()
        (data_dir / 'state.json').write_text(json.dumps({'settings': {'model': 'test:latest', 'project_path': str(project)}, 'chats': []}))
        ollama = HTTPServer(('127.0.0.1', 0), OllamaMock)
        thread = threading.Thread(target=ollama.serve_forever, daemon=True)
        thread.start()
        env = {**os.environ, 'BIGASERE_DATA_DIR': str(data_dir), 'BIGASERE_OLLAMA_URL': f'http://127.0.0.1:{ollama.server_port}'}
        proc = subprocess.Popen([sys.executable, '-u', str(SCRIPT)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        try:
            line = proc.stdout.readline().strip()
            _, port, token = line.split(' ')
            root = f'http://127.0.0.1:{port}'
            sess = requests.Session()
            assert sess.get(root + '/api/status').status_code == 401
            assert sess.get(root + '/launch?token=invalid').status_code == 403
            r = sess.get(root + '/launch?token=' + token)
            assert r.status_code == 200
            assert '<title>Big Asere AI' in r.text
            status = sess.get(root + '/api/status').json()
            assert status['ollama']['online']
            assert 'test:latest' in status['ollama']['models']
            h={'X-BigAsere-Request':'1'}
            denied = sess.post(root+'/api/chats', data='{}', headers={'Origin':'http://evil.example','X-BigAsere-Request':'1'})
            assert denied.status_code == 403
            assert sess.post(root+'/api/chats', data='{}').status_code == 403
            p=sess.get(root+'/api/project').json()
            diag=sess.get(root+'/api/diagnostics').json()
            assert diag['version']=='2.2.1'
            assert diag['project_path']==str(project)
            assert diag['existing_scripts']['asistente.py'] is False
            assert p['configured']
            assert 'hello.py' in p['files']
            assert '.env' not in p['files']
            assert 'credentials.json' not in p['files']
            assert sess.get(root+'/api/project/file',params={'path':'../outside.py'}).status_code == 400
            assert sess.get(root+'/api/project/file',params={'path':'hello.py'}).json()['content'] == 'print("Hola Big Asere")\n'
            create = sess.post(root+'/api/chats',json={},headers=h)
            assert create.status_code == 201
            chat_id=create.json()['chat']['id']
            invalid=sess.post(root+f'/api/chats/{chat_id}/message',json={'content':'Hola','mode':['bad']},headers=h)
            assert invalid.status_code == 400
            assert sess.post(root+f'/api/chats/{chat_id}/rename',json={'title':'Análisis local'},headers=h).status_code == 200
            assert sess.get(root+f'/api/chats/{chat_id}').json()['chat']['title']=='Análisis local'
            result=sess.post(root+f'/api/chats/{chat_id}/message',json={'content':'Hola', 'files':['notes.md'], 'include_git':False,'mode':'auditoria'},headers=h,timeout=15)
            assert result.status_code == 200
            events = [json.loads(x) for x in result.text.strip().split('\n')]
            assert ''.join(e['text'] for e in events if e['type']=='delta') == 'Hola desde Ollama'
            assert events[-1]['type'] == 'done'
            saved=sess.get(root+f'/api/chats/{chat_id}').json()['chat']
            assert [x['role'] for x in saved['messages']] == ['user','assistant']
            assert saved['messages'][1]['content']=='Hola desde Ollama'
            assert saved['messages'][0]['mode']=='auditoria'
            assert sess.delete(root+f'/api/chats/{chat_id}',headers=h).status_code == 200
            assert sess.get(root+f'/api/chats/{chat_id}').status_code == 404
            assert json.loads((data_dir/'state.json').read_text())['chats'] == []
            assert sess.post(root+'/api/settings',json={'system_prompt':'Prueba'},headers=h).status_code == 200
        finally:
            proc.terminate()
            proc.wait(timeout=5)
            ollama.shutdown()
