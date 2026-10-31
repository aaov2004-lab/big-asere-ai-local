#!/usr/bin/env python3
"""Big Asere AI Local – loopback-only, stdlib Python server for Ollama.

No external Python dependencies, no code execution, and read-only project access.
"""
import json
import re
import os
import secrets
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VERSION = '2.2.1'
APP_DIR = Path(os.environ.get('BIGASERE_DATA_DIR', Path.home() / 'Library' / 'Application Support' / 'Big Asere AI'))
RESOURCES = Path(__file__).resolve().parent
OLLAMA_URL = os.environ.get('BIGASERE_OLLAMA_URL', 'http://127.0.0.1:11434').rstrip('/')
_ollama_address = urllib.parse.urlsplit(OLLAMA_URL)
if _ollama_address.scheme != 'http' or _ollama_address.hostname not in {'127.0.0.1', 'localhost', '::1'} or _ollama_address.username or _ollama_address.password:
    raise RuntimeError('Ollama debe estar en una dirección HTTP local (localhost).')
LOCAL_HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))
SESSION = secrets.token_urlsafe(36)
LOCK = threading.RLock()
BUSY = set()
STATE_FILE = APP_DIR / 'state.json'
DEFAULT_SETTINGS = {
    'model': 'qwen2.5-coder:7b',
    'project_path': '',
    'system_prompt': 'Eres Big Asere AI, un asistente local que responde en español. Sé claro y práctico. Para temas de código, distingue hechos verificados de suposiciones. No afirmes que leíste un archivo o ejecutaste comandos a menos que esa información se incluya explícitamente en el contexto. No sugieras cambios en producción sin revisión y aprobación.',
}

MODES = {
    'general': 'Responde con claridad y explica los términos técnicos. No inventes acceso a archivos ni a internet.',
    'codigo': 'Eres un revisor de código. Explica la lógica y propone cambios con ejemplos, pero recuerda que NO puedes editar, compilar ni ejecutar código desde esta aplicación.',
    'auditoria': 'Actúa como auditor de solo lectura. Separa hechos comprobados con el contexto recibido, riesgos, incertidumbres y pruebas sugeridas. Nunca afirmes que algo está seguro sin evidencia.',
    'plan': 'Organiza el trabajo en prioridades, dependencias y pasos verificables. No afirme haber creado tareas, PR o cambios reales.',
}


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def load_state():
    APP_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(APP_DIR, 0o700)
    try:
        data = json.loads(STATE_FILE.read_text(encoding='utf-8'))
        if isinstance(data, dict) and isinstance(data.get('chats'), list):
            current = data.get('settings') if isinstance(data.get('settings'), dict) else {}
            data['settings'] = {**DEFAULT_SETTINGS, **current}
            return data
    except (OSError, ValueError):
        pass
    return {'settings': dict(DEFAULT_SETTINGS), 'chats': []}


STATE = load_state()


def save_state():
    APP_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(APP_DIR, 0o700)
    temp = STATE_FILE.with_name('state.' + secrets.token_hex(6) + '.tmp')
    fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as handle:
        json.dump(STATE, handle, ensure_ascii=False, indent=2)
    os.replace(str(temp), str(STATE_FILE))
    try:
        os.chmod(STATE_FILE, 0o600)
    except OSError:
        pass


def find_chat(chat_id):
    return next((c for c in STATE['chats'] if c['id'] == chat_id), None)


def query_ollama(path, payload=None, timeout=3):
    data = None if payload is None else json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(OLLAMA_URL + path, data=data, headers={'Content-Type': 'application/json'} if payload is not None else {}, method='POST' if payload is not None else 'GET')
    return LOCAL_HTTP.open(req, timeout=timeout)


def model_status():
    try:
        with query_ollama('/api/tags') as response:
            obj = json.load(response)
        models = [x.get('name', '') for x in obj.get('models', []) if x.get('name')]
        return {'online': True, 'models': models, 'error': ''}
    except Exception:
        return {'online': False, 'models': [], 'error': 'Ollama no está respondiendo en 127.0.0.1:11434.'}


OMIT_DIRS = {'.git', 'node_modules', '.next', 'dist', 'build', '.venv', 'venv', '__pycache__', '.DS_Store', '.cache', '.turbo', '.output', 'coverage'}
ALLOW_EXT = {'.md', '.txt', '.py', '.js', '.jsx', '.ts', '.tsx', '.json', '.html', '.css', '.scss', '.sql', '.yml', '.yaml', '.sh', '.toml', '.xml', '.vue', '.svelte', '.go', '.rs', '.java', '.swift', '.kt', '.rb', '.php'}
DENY_TERMS = {'secret', 'credential', 'private', 'token', 'password', 'api-key', 'apikey', 'service-account', 'ssh', 'keyfile', 'id_rsa', 'id_ed25519', 'auth.json', 'config.json'}
DENY_SUFFIX = {'.pem', '.key', '.p12', '.pfx', '.db', '.sqlite', '.sqlite3'}


def permitted_file(name):
    low = name.lower()
    if low.startswith('.') or low.endswith(tuple(DENY_SUFFIX)):
        return False
    if any(part in low for part in DENY_TERMS):
        return False
    return Path(low).suffix in ALLOW_EXT and not (low in {'package-lock.json', 'pnpm-lock.yaml', 'yarn.lock'})


# Conservative, best-effort redaction. Never mistake this for a secret scanner.
SENSITIVE_ASSIGNMENT = re.compile(
    r'(?im)^(\s*(?:export\s+)?[\w.-]*(?:API[_-]?KEY|SECRET|PASSWORD|AUTH[_-]?TOKEN|PRIVATE[_-]?KEY|SERVICE[_-]?ROLE)[\w.-]*\s*[:=]\s*)(.+)$'
)
TOKEN_LIKE = re.compile(r'(?i)\b(?:sk_(?:live|test)_[A-Za-z0-9]{8,}|ghp_[A-Za-z0-9]{12,}|sk-[A-Za-z0-9_-]{16,})\b')
PRIVATE_KEY = re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----')


def redact_for_model(text):
    text = PRIVATE_KEY.sub('[CLAVE PRIVADA OCULTA]', text)
    text = TOKEN_LIKE.sub('[TOKEN OCULTO]', text)
    return SENSITIVE_ASSIGNMENT.sub(lambda m: m.group(1) + '[VALOR OCULTO]', text)


def project_root():
    path = STATE['settings'].get('project_path', '')
    if not path:
        return None
    root = Path(path).expanduser().resolve()
    return root if root.is_dir() else None


def project_files():
    root = project_root()
    if not root:
        return []
    files = []
    for dirname, dirs, names in os.walk(str(root), followlinks=False):
        rel_dir = Path(dirname).relative_to(root)
        if len(rel_dir.parts) >= 7:
            dirs[:] = []
            continue
        dirs[:] = sorted(d for d in dirs if d not in OMIT_DIRS and not d.startswith('.') and not Path(dirname, d).is_symlink())
        for name in sorted(names):
            if not permitted_file(name):
                continue
            candidate = Path(dirname) / name
            if candidate.is_symlink():
                continue
            try:
                if candidate.stat().st_size > 120_000:
                    continue
            except OSError:
                continue
            files.append(str(candidate.relative_to(root)))
            if len(files) >= 350:
                return files
    return files


def safe_read(rel_path):
    root = project_root()
    if not root or not isinstance(rel_path, str) or len(rel_path) > 300:
        raise ValueError('Primero selecciona una carpeta del proyecto.')
    if Path(rel_path).is_absolute() or '..' in Path(rel_path).parts:
        raise ValueError('Ruta no permitida.')
    file_path = (root / rel_path).resolve()
    if not str(file_path).startswith(str(root) + os.sep) or not permitted_file(file_path.name):
        raise ValueError('Archivo no permitido.')
    if not file_path.is_file() or file_path.is_symlink() or file_path.stat().st_size > 120_000:
        raise ValueError('Archivo no disponible o demasiado grande.')
    return file_path.read_text(encoding='utf-8', errors='replace')[:80_000]


def git_info():
    root = project_root()
    if not root:
        return {'configured': False, 'path': '', 'git': False, 'status': '', 'log': '', 'files': []}
    def git(*args):
        try:
            result = subprocess.run(
                ['git', '-c', 'core.fsmonitor=false', '-c', 'submodule.recurse=false',
                 '-C', str(root), *args], capture_output=True, text=True,
                timeout=5, check=False,
                env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0',
                     'GIT_TERMINAL_PROMPT': '0', 'GIT_NO_LAZY_FETCH': '1',
                     'GIT_CONFIG_NOSYSTEM': '1', 'GIT_EXTERNAL_DIFF': '/usr/bin/false'}
            )
            return result.stdout[:9000] if result.returncode == 0 else ''
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return ''
    branch = git('rev-parse', '--is-inside-work-tree').strip() == 'true'
    return {
        'configured': True, 'path': str(root), 'git': branch,
        'status': git('status', '--short', '--branch') if branch else '',
        'log': git('log', '-5', '--pretty=format:%h %s') if branch else '',
        'files': project_files(),
        'branch': git('branch', '--show-current').strip() if branch else '',
        'diffstat': git('diff', '--no-ext-diff', '--no-textconv', '--stat') if branch else '',
    }


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = 'BigAsereAI/1.0'

    def log_message(self, fmt, *args):
        if os.environ.get('BIGASERE_DEBUG') == '1':
            super().log_message(fmt, *args)

    def send_data(self, code, body, content_type='application/json', cookies=None):
        if content_type == 'application/json':
            body = json.dumps(body, ensure_ascii=False).encode('utf-8')
        elif isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', content_type + ('; charset=utf-8' if content_type.startswith('text/') or content_type == 'application/json' else ''))
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Connection', 'close')
        self.close_connection = True
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        if cookies:
            self.send_header('Set-Cookie', cookies)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def allowed_host(self):
        # Reduce DNS-rebinding risks: never accept another hostname.
        return self.headers.get('Host', '') == '127.0.0.1:' + str(self.server.server_port)

    def authenticated(self):
        return ('ba_session=' + SESSION) in self.headers.get('Cookie', '').split('; ')

    def require_auth(self, mutation=False):
        if not self.allowed_host():
            self.send_data(HTTPStatus.FORBIDDEN, {'error': 'Dirección local no autorizada.'})
            return False
        if not self.authenticated():
            self.send_data(HTTPStatus.UNAUTHORIZED, {'error': 'Sesión local no autorizada.'})
            return False
        if mutation:
            if self.headers.get('X-BigAsere-Request') != '1':
                self.send_data(HTTPStatus.FORBIDDEN, {'error': 'Solicitud no autorizada.'})
                return False
            origin = self.headers.get('Origin', '')
            if origin and origin != ('http://127.0.0.1:' + str(self.server.server_port)):
                self.send_data(HTTPStatus.FORBIDDEN, {'error': 'Origen no autorizado.'})
                return False
        return True

    def body(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
            if length < 1 or length > 1_000_000:
                raise ValueError('Solicitud vacía o excesiva.')
            obj = json.loads(self.rfile.read(length))
            if not isinstance(obj, dict):
                raise ValueError('JSON inválido.')
            return obj
        except (ValueError, UnicodeDecodeError):
            raise ValueError('Datos de solicitud no válidos.')

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        if path == '/launch':
            if not self.allowed_host():
                self.send_data(403, {'error': 'Dirección no autorizada.'})
                return
            supplied = urllib.parse.parse_qs(parsed.query).get('token', [''])[0]
            if not secrets.compare_digest(supplied, SESSION):
                self.send_data(HTTPStatus.FORBIDDEN, {'error': 'Enlace de apertura inválido.'})
                return
            self.send_response(302)
            self.send_header('Location', '/')
            self.send_header('Set-Cookie', 'ba_session=' + SESSION + '; HttpOnly; SameSite=Lax; Path=/')
            self.send_header('Content-Length', '0')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            return
        if not self.require_auth():
            return
        if path in {'/', '/index.html', '/app.js', '/styles.css'}:
            fname = {'/': 'index.html', '/index.html': 'index.html', '/app.js': 'app.js', '/styles.css': 'styles.css'}[path]
            typ = 'text/html' if fname.endswith('html') else ('text/javascript' if fname.endswith('js') else 'text/css')
            self.send_data(200, (RESOURCES / fname).read_bytes(), typ)
            return
        if path == '/api/status':
            with LOCK:
                settings = dict(STATE['settings'])
            self.send_data(200, {'version': VERSION, 'ollama': model_status(), 'settings': settings})
            return
        if path == '/api/chats':
            with LOCK:
                chats = [{'id': c['id'], 'title': c['title'], 'updated': c['updated']} for c in reversed(STATE['chats'])]
            self.send_data(200, {'chats': chats})
            return
        if path.startswith('/api/chats/'):
            chat_id = path[len('/api/chats/'):]
            with LOCK:
                chat = find_chat(chat_id)
                obj = json.loads(json.dumps(chat)) if chat else None
            self.send_data(200, {'chat': obj}) if obj else self.send_data(404, {'error': 'Chat no encontrado.'})
            return
        if path == '/api/diagnostics':
            root = project_root()
            with LOCK:
                settings = dict(STATE['settings'])
                count = len(STATE['chats'])
            self.send_data(200, {
                'version': VERSION, 'python': sys.version.split()[0],
                'data_path': str(APP_DIR), 'ollama_url': OLLAMA_URL,
                'project_path': str(root) if root else '',
                'git_available': bool(__import__('shutil').which('git')),
                'conversations': count,
                'existing_scripts': {
                    'asistente.py': bool(root and (root / 'asistente.py').is_file()),
                    'puente_big_asere.py': bool(root and (root / 'puente_big_asere.py').is_file()),
                },
                'note': 'Los scripts existentes no se ejecutan ni se integran automáticamente.',
            })
            return
        if path == '/api/project':
            self.send_data(200, git_info())
            return
        if path == '/api/project/file':
            rel = urllib.parse.parse_qs(parsed.query).get('path', [''])[0]
            try:
                self.send_data(200, {'path': rel, 'content': safe_read(rel)})
            except (OSError, ValueError) as e:
                self.send_data(400, {'error': str(e)})
            return
        self.send_data(404, {'error': 'No encontrado.'})

    def do_DELETE(self):
        if not self.require_auth(mutation=True):
            return
        path = urllib.parse.urlsplit(self.path).path
        if not path.startswith('/api/chats/'):
            self.send_data(404, {'error': 'No encontrado.'})
            return
        chat_id = path[len('/api/chats/'):]
        with LOCK:
            if chat_id in BUSY:
                self.send_data(409, {'error': 'Espera a que termine la respuesta.'})
                return
            STATE['chats'] = [c for c in STATE['chats'] if c['id'] != chat_id]
            save_state()
        self.send_data(200, {'ok': True})

    def do_POST(self):
        if not self.require_auth(mutation=True):
            return
        path = urllib.parse.urlsplit(self.path).path
        try:
            if path == '/api/chats':
                with LOCK:
                    chat = {'id': uuid.uuid4().hex, 'title': 'Nueva conversación', 'updated': now(), 'messages': []}
                    STATE['chats'].append(chat)
                    save_state()
                self.send_data(201, {'chat': chat})
                return
            if path.startswith('/api/chats/') and path.endswith('/rename'):
                chat_id = path[len('/api/chats/'):-len('/rename')].rstrip('/')
                obj = self.body()
                title = obj.get('title', '')
                if not isinstance(title, str) or not 1 <= len(title.strip()) <= 90:
                    raise ValueError('Escribe un nombre de 1 a 90 caracteres.')
                with LOCK:
                    chat = find_chat(chat_id)
                    if not chat:
                        self.send_data(404, {'error': 'Chat no encontrado.'})
                        return
                    chat['title'] = title.strip()
                    chat['updated'] = now()
                    save_state()
                self.send_data(200, {'ok': True})
                return
            if path == '/api/settings':
                obj = self.body()
                with LOCK:
                    if isinstance(obj.get('model'), str) and 0 < len(obj['model']) <= 120:
                        STATE['settings']['model'] = obj['model']
                    if isinstance(obj.get('system_prompt'), str) and len(obj['system_prompt']) <= 4000:
                        STATE['settings']['system_prompt'] = obj['system_prompt']
                    save_state()
                self.send_data(200, {'settings': STATE['settings']})
                return
            if path == '/api/project/select':
                # Folder access only after a deliberate Finder dialog.
                if sys.platform != 'darwin':
                    self.send_data(400, {'error': 'La selección visual de carpetas funciona en macOS.'})
                    return
                script = 'POSIX path of (choose folder with prompt "Selecciona el proyecto para Big Asere AI (solo lectura)")'
                result = subprocess.run(['/usr/bin/osascript', '-e', script], capture_output=True, text=True, timeout=120, check=False)
                folder = result.stdout.strip()
                if result.returncode != 0 or not folder:
                    self.send_data(400, {'error': 'No se seleccionó ninguna carpeta.'})
                    return
                root = Path(folder).resolve()
                if not root.is_dir():
                    raise ValueError('Carpeta no válida.')
                with LOCK:
                    STATE['settings']['project_path'] = str(root)
                    save_state()
                self.send_data(200, {'path': str(root)})
                return
            if path == '/api/project/clear':
                with LOCK:
                    STATE['settings']['project_path'] = ''
                    save_state()
                self.send_data(200, {'ok': True})
                return
            if path == '/api/ollama/start':
                if sys.platform != 'darwin':
                    self.send_data(400, {'error': 'Disponible solamente en macOS.'})
                    return
                result = subprocess.run(['/usr/bin/open', '-a', 'Ollama'], capture_output=True, text=True, timeout=12, check=False)
                self.send_data(200 if result.returncode == 0 else 400, {'ok': result.returncode == 0, 'error': (result.stderr or 'No se encontró la aplicación Ollama.').strip() if result.returncode else ''})
                return
            if path.startswith('/api/chats/') and path.endswith('/message'):
                self.stream_chat(path[len('/api/chats/'):-len('/message')].rstrip('/'), self.body())
                return
            self.send_data(404, {'error': 'No encontrado.'})
        except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
            self.send_data(400, {'error': str(exc)})

    def stream_chat(self, chat_id, obj):
        content = obj.get('content', '')
        attached = obj.get('files', [])
        include_git = obj.get('include_git', False) is True
        mode = obj.get('mode', 'general')
        if not isinstance(mode, str) or mode not in MODES:
            self.send_data(400, {'error': 'Perfil de asistencia no válido.'})
            return
        if not isinstance(content, str) or not content.strip() or len(content) > 16000:
            self.send_data(400, {'error': 'Escribe un mensaje de hasta 16 000 caracteres.'})
            return
        if not isinstance(attached, list) or len(attached) > 4 or any(not isinstance(p, str) for p in attached):
            self.send_data(400, {'error': 'Puedes adjuntar hasta 4 archivos de texto.'})
            return
        # Explicitly chosen attachments only; never upload the repository unprompted.
        attachments = []
        try:
            for rel in attached:
                attachments.append((rel, redact_for_model(safe_read(rel)[:12_000])))
        except (ValueError, OSError) as exc:
            self.send_data(400, {'error': str(exc)})
            return
        with LOCK:
            chat = find_chat(chat_id)
            if not chat:
                self.send_data(404, {'error': 'Chat no encontrado.'})
                return
            if chat_id in BUSY:
                self.send_data(409, {'error': 'Ya hay una respuesta en curso.'})
                return
            BUSY.add(chat_id)
            model = STATE['settings']['model']
            system = STATE['settings']['system_prompt']
            previous = [
                {'role': m['role'], 'content': m['content'][:6_000]}
                for m in chat['messages'][-12:]
                if m.get('role') in ('user', 'assistant') and isinstance(m.get('content'), str)
            ]
            chat['messages'].append({'role': 'user', 'content': content, 'files': attached, 'git': include_git, 'mode': mode})
            if len(chat['messages']) == 1:
                chat['title'] = content.replace('\n', ' ')[:48]
            chat['updated'] = now()
            save_state()
        # Never forward a missing or misspelled model to Ollama without explanation.
        installed = model_status()
        if not installed['online']:
            with LOCK:
                chat = find_chat(chat_id)
                if chat and chat['messages'] and chat['messages'][-1].get('content') == content:
                    chat['messages'].pop()
                    save_state()
                BUSY.discard(chat_id)
            self.send_data(503, {'error': 'Ollama está desconectado. Abre Ollama y verifica la conexión.'})
            return
        if model not in installed['models']:
            with LOCK:
                chat = find_chat(chat_id)
                if chat and chat['messages'] and chat['messages'][-1].get('content') == content:
                    chat['messages'].pop()
                    save_state()
                BUSY.discard(chat_id)
            self.send_data(400, {'error': 'El modelo seleccionado no está instalado. Elige uno que aparezca en Ollama.'})
            return
        additional = []
        if include_git:
            p = git_info()
            if p['git']:
                additional.append('ESTADO GIT (solo lectura; obtenido ahora):\n' + redact_for_model(p['status']) + '\nÚLTIMOS COMMITS:\n' + redact_for_model(p['log']))
        for name, text in attachments:
            additional.append('ARCHIVO ADJUNTADO POR USUARIO: ' + name + '\n```\n' + text + '\n```')
        latest = content + ('\n\nCONTEXTO EXPLÍCITO:\n' + '\n\n'.join(additional) if additional else '')
        payload = {'model': model, 'stream': True, 'messages': [{'role': 'system', 'content': system + '\n\nMODO ACTUAL: ' + MODES[mode]}, *previous, {'role': 'user', 'content': latest}]}
        response = ''
        error = None
        begun = False
        try:
            request = urllib.request.Request(OLLAMA_URL + '/api/chat', data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
            with LOCAL_HTTP.open(request, timeout=180) as upstream:
                self.send_response(200)
                self.send_header('Content-Type', 'application/x-ndjson; charset=utf-8')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Connection', 'close')
                self.end_headers()
                begun = True
                for line in upstream:
                    try:
                        item = json.loads(line)
                    except (ValueError, TypeError):
                        continue
                    piece = item.get('message', {}).get('content', '')
                    if piece:
                        response += piece
                        if len(response) > 300_000:
                            error = 'Respuesta demasiado larga; se detuvo.'
                            break
                        encoded = json.dumps({'type': 'delta', 'text': piece}, ensure_ascii=False).encode('utf-8') + b'\n'
                        self.wfile.write(encoded)
                        self.wfile.flush()
                    if item.get('error'):
                        error = str(item['error'])
                    if item.get('done'):
                        break
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            error = str(exc)
            if not begun:
                self.send_data(502, {'error': 'No se pudo conectar con Ollama: ' + error})
        except (BrokenPipeError, ConnectionResetError):
            # Client may have pressed Stop; preserve partial response.
            pass
        finally:
            with LOCK:
                chat = find_chat(chat_id)
                if chat and response:
                    chat['messages'].append({'role': 'assistant', 'content': response})
                    chat['updated'] = now()
                BUSY.discard(chat_id)
                save_state()
            if begun:
                try:
                    self.wfile.write((json.dumps({'type': 'done', 'error': error}, ensure_ascii=False) + '\n').encode('utf-8'))
                    self.wfile.flush()
                except (OSError, BrokenPipeError):
                    pass


def main():
    host = '127.0.0.1'
    class LoopbackServer(ThreadingHTTPServer):
        allow_reuse_address = False

    with LoopbackServer((host, 0), Handler) as server:
        server.daemon_threads = True
        port = server.server_port
        print('READY {} {}'.format(port, SESSION), flush=True)
        try:
            server.serve_forever(poll_interval=0.2)
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
