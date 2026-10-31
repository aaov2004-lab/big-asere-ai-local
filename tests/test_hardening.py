"""Security checks for the local-only backend. Does not connect to the Internet."""
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import requests

SERVER = Path(__file__).resolve().parents[1] / 'BigAsereAI' / 'Resources' / 'server.py'


def get_module():
    spec = importlib.util.spec_from_file_location('ba_server_security', SERVER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_secret_redaction_and_path_checks():
    module = get_module()
    sample = '''API_KEY=very-secret-value\nservice_role_secret: abcd\nSTRIPE_SECRET_KEY = sk_live_abcde11111\ntext=ghp_01234567890123456789\n-----BEGIN PRIVATE KEY-----\nxyz\n-----END PRIVATE KEY-----\n'''
    cleaned = module.redact_for_model(sample)
    assert 'very-secret-value' not in cleaned
    assert 'sk_live_' not in cleaned
    assert 'ghp_01234' not in cleaned
    assert '-----BEGIN' not in cleaned
    assert module.permitted_file('readme.md')
    assert not module.permitted_file('credentials.json')
    assert not module.permitted_file('.env')
    assert not module.permitted_file('keys.pem')


class StubOllama(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({'models': [{'name': 'ok:model'}]}).encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def test_host_restriction_and_missing_model():
    with tempfile.TemporaryDirectory() as td:
        app_dir = Path(td) / 'data'
        app_dir.mkdir()
        (app_dir / 'state.json').write_text(json.dumps({'settings': {'model': 'not-installed'}, 'chats': []}))
        mock = HTTPServer(('127.0.0.1', 0), StubOllama)
        threading.Thread(target=mock.serve_forever, daemon=True).start()
        env = {**os.environ, 'BIGASERE_DATA_DIR': str(app_dir), 'BIGASERE_OLLAMA_URL': f'http://127.0.0.1:{mock.server_port}'}
        proc = subprocess.Popen([sys.executable, '-u', str(SERVER)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            ready = proc.stdout.readline().strip().split(' ')
            assert ready[0] == 'READY'
            host = f'127.0.0.1:{ready[1]}'
            url = 'http://' + host
            browser = requests.Session()
            wrong_host = browser.get(url+'/launch?token='+ready[2], headers={'Host': 'malicious.test'})
            assert wrong_host.status_code == 403
            valid = browser.get(url+'/launch?token='+ready[2])
            assert valid.status_code == 200
            assert browser.get(url+'/api/status', headers={'Host':'malicious.test'}).status_code == 403
            create = browser.post(url+'/api/chats', json={}, headers={'X-BigAsere-Request':'1'})
            chat_id = create.json()['chat']['id']
            rejected = browser.post(url+f'/api/chats/{chat_id}/message',json={'content':'Prueba'},headers={'X-BigAsere-Request':'1'})
            assert rejected.status_code == 400
            assert 'no está instalado' in rejected.json()['error']
            chat = browser.get(url+f'/api/chats/{chat_id}').json()['chat']
            assert chat['messages'] == []
        finally:
            proc.terminate()
            proc.wait(timeout=5)
            mock.shutdown()
