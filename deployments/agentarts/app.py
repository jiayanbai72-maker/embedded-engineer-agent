"""AgentRun HTTP adapter. Local core/start scripts stay untouched.

First release: authenticated team demo, session-scoped document engineering.
No host code execution, arbitrary paths, local Keil, USB or remote worker claims.
"""
import argparse
import base64
from copy import deepcopy
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading
import time
from uuid import uuid4
from urllib.parse import urlsplit
from embedded_agent.service import EngineeringService
from embedded_agent.control import DecisionController
from embedded_agent.autonomy import AutonomousRunner, ModelDecider
from .model_adapter import configured

ROOT = Path(__file__).resolve().parents[2]
ALLOWED = {'analysis', 'search_documents', 'read_document_page', 'read_parameter', 'ask', 'finish', 'execute',
           'design_plan', 'design_research', 'design_evaluate', 'design_recommend', 'power_estimate', 'selection_check'}
SESSION = re.compile(r'[A-Za-z0-9_-]{1,64}')
STATE_FILE = re.compile(r'runtime/(?:projects/[a-f0-9-]{36}|control-runs/[a-f0-9-]{36}|knowledge/parameters/PAR-[a-f0-9]{32})\.json')


class CloudController(DecisionController):
    def context(self, run_id):
        context = super().context(run_id)
        context['allowed_actions'] = [a for a in context['allowed_actions'] if a in ALLOWED]
        context['action_contracts'] = {k: v for k, v in context['action_contracts'].items() if k in ALLOWED}
        context['capabilities'] = ['documents.search', 'documents.page', 'parameters.read', 'constraint_check', 'documents.zip']
        context['deployment'] = {'scope': 'cloud_document_engineering', 'local_worker': 'not_connected',
                                 'code_execution': 'disabled', 'hardware': 'not_run'}
        for item in context['capability_status']['items']:
            if item['id'] in ('keil_build', 'armcc_build', 'host_validation', 'hardware_execution'):
                item.update(status='requires_local_worker', detail='云端入口禁止执行；本地执行端尚未接入')
        return context

    def submit(self, run_id, revision, decision):
        if not isinstance(decision, dict) or decision.get('action') not in ALLOWED:
            raise ValueError('此云端版本不允许该工具；本地执行端尚未接入')
        if decision['action'] == 'analysis' and decision.get('arguments', {}).get('decision', {}).get('actions') != ['export_documents']:
            raise ValueError('首版云端仅支持文档交付；构建和硬件工具需本地执行端')
        return super().submit(run_id, revision, decision)

    def plan(self, run_id, revision, proposal):
        if not isinstance(proposal, dict) or any(t.get('action') not in ALLOWED | {'user_input'} for t in proposal.get('tasks', [])):
            raise ValueError('任务计划包含未接入的云端工具')
        return super().plan(run_id, revision, proposal)


class Checkpoints:
    """Immutable JSON generations; avoids SQLite/rename locking on FUSE mounts.

    Demo scope: one application writer per platform session. Not distributed SQL.
    """
    def __init__(self, folder):
        self.folder = Path(folder); self.folder.mkdir(parents=True, exist_ok=True)

    def restore(self, workspace):
        candidates = sorted(self.folder.glob('checkpoint-*.json'), reverse=True)
        for file in candidates:
            try:
                if file.stat().st_size > 16_000_000: continue
                envelope = json.loads(file.read_text(encoding='utf-8'))
                payload = envelope['payload']
                raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
                if hashlib.sha256(raw).hexdigest() != envelope['sha256'] or payload['schema_version'] != 1: continue
                entries = payload['files']
                if not isinstance(entries, dict) or any(not STATE_FILE.fullmatch(k) for k in entries): continue
                for relative, data in entries.items():
                    path = workspace / relative; path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
                return True
            except (OSError, ValueError, KeyError, TypeError): continue
        if candidates: raise ValueError('没有完整可恢复的会话快照，未创建空项目覆盖历史')
        return False

    def save(self, workspace):
        files = {}
        for base in ('runtime/projects', 'runtime/control-runs', 'runtime/knowledge/parameters'):
            for file in (workspace / base).glob('*.json'):
                relative = file.relative_to(workspace).as_posix()
                if STATE_FILE.fullmatch(relative): files[relative] = json.loads(file.read_text(encoding='utf-8'))
        payload = {'schema_version': 1, 'files': files}
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
        if len(raw) > 8_000_000: raise ValueError('会话状态超过首版8MB上限，请导出记录后新建会话')
        envelope = {'payload': payload, 'sha256': hashlib.sha256(raw).hexdigest()}
        file = self.folder / ('checkpoint-' + str(time.time_ns()).zfill(20) + '-' + uuid4().hex + '.json')
        with file.open('x', encoding='utf-8') as stream:
            json.dump(envelope, stream, ensure_ascii=False); stream.flush()
        # Keep the latest complete generations for interrupted-write recovery.
        old = sorted(self.folder.glob('checkpoint-*.json'), reverse=True)[5:]
        for prior in old: prior.unlink(missing_ok=True)


class Kernel:
    def __init__(self, source, state, scratch, provider=None):
        self.source, self.state, self.scratch = Path(source), Path(state), Path(scratch)
        self.provider = provider
        self.sessions = {}; self.lock = threading.Lock()

    def session(self, session_id):
        if not isinstance(session_id, str) or not SESSION.fullmatch(session_id): raise ValueError('需要有效的X-Hw-Agentarts-Session-Id（1至64个字母、数字、下划线或中划线）')
        key = hashlib.sha256(session_id.encode()).hexdigest()
        with self.lock:
            if key not in self.sessions:
                if len(self.sessions) >= 64: raise ValueError('当前进程会话数量达到64个上限')
                workspace = self.scratch / key
                if not workspace.resolve().is_relative_to(self.scratch.resolve()): raise ValueError('临时会话目录越界')
                if workspace.exists(): shutil.rmtree(workspace)
                (workspace / 'knowledge').mkdir(parents=True)
                shutil.copyfile(self.source / 'knowledge/index.json', workspace / 'knowledge/index.json')
                if (self.source / 'docs').is_dir(): shutil.copytree(self.source / 'docs', workspace / 'docs')
                # Immutable packaged knowledge can be shared read-only; mutable index is scratch.
                official = self.source / 'knowledge/official'
                if official.is_dir():
                    try: (workspace / 'knowledge/official').symlink_to(official, target_is_directory=True)
                    except OSError: shutil.copytree(official, workspace / 'knowledge/official')
                checkpoints = Checkpoints(self.state / key)
                checkpoints.restore(workspace)
                service = EngineeringService(workspace)
                if service.app.documents.catalog.is_file(): service.app.documents.build()
                controller = CloudController(service)
                self.sessions[key] = (service, controller, AutonomousRunner(controller, self.provider), checkpoints, workspace, threading.RLock())
            return self.sessions[key]

    def invoke(self, session_id, payload):
        if not isinstance(payload, dict): raise ValueError('请求必须为JSON对象')
        service, control, runner, checkpoints, workspace, lock = self.session(session_id)
        with lock:
            action = payload.get('action', 'start' if payload.get('message') else 'status')
            if action == 'start':
                project = service.create(payload.get('description', payload.get('message')))
                run = control.create(project['id'], max_steps=20, max_repairs=3)
            else:
                run = control.load(payload.get('run_id', ''))
                project = service.get(run['project_id'])
            message = '项目已创建，等待模型判断' if action == 'start' else '已读取当前状态'
            if action in ('confirm', 'select', 'supplement', 'design_accept', 'continue_selection', 'proceed_estimated_design'):
                args = {'confirmed': True} if action in ('confirm', 'continue_selection') else {'candidate_id': payload.get('candidate_id')} if action == 'select' else {'message': payload.get('message')}
                if action == 'design_accept': args = {'candidate_id': payload.get('candidate_id'), 'confirmed': True}
                if action == 'proceed_estimated_design':
                    args = {'candidate_id': payload.get('candidate_id'), 'confirmed': True, 'accept_open_items': payload.get('accept_open_items'), 'rationale': payload.get('rationale')}
                # Require current revision: a stale UI must never confirm revised requirements.
                changed = service.update(project['id'], payload.get('project_revision'), action, args)
                if action == 'design_accept': service.update(project['id'], changed['revision'], 'continue_selection', {'confirmed': True})
            elif action == 'reply':
                control.reply(run['id'], payload.get('run_revision'), payload.get('message'))
            elif action == 'download':
                raw = service.download(project['id'])
                return {'status': 'download', 'filename': 'project-documents.zip', 'base64': base64.b64encode(raw).decode(), 'sha256': hashlib.sha256(raw).hexdigest()}
            elif action not in ('start', 'continue', 'status'):
                raise ValueError('云端操作不支持')
            status = 'idle'
            if action != 'status':
                # Commit user actions before model/network calls. At most two bounded steps per HTTP request.
                checkpoints.save(workspace)
                for _ in range(2):
                    result = runner.step(run['id']); status = result['status']; message = result['message']
                    checkpoints.save(workspace)
                    if status != 'continue': break
            context = control.context(run['id'])
            return {'status': status, 'message': message, 'project': context['project'], 'run': context['run'],
                    'progress': context['task_progress'], 'deployment': context['deployment'],
                    'storage_scope': 'same_platform_session_only', 'model_connected': self.provider is not None}


def make_server(kernel, host='127.0.0.1', port=8786, *, trust_gateway=False, app_token=None):
    if host not in ('127.0.0.1', 'localhost') and not trust_gateway and not app_token:
        raise ValueError('非本地监听需要平台网关鉴权或应用认证令牌')
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def send(self, code, value):
            raw = json.dumps(value, ensure_ascii=False).encode()
            self.send_response(code); self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Cache-Control', 'no-store'); self.send_header('Content-Length', str(len(raw)))
            self.end_headers(); self.wfile.write(raw)
        def do_GET(self):
            path = urlsplit(self.path).path
            if path in ('/ping', '/health'):
                return self.send(200, {'status': 'Healthy', 'scope': 'agentarts_document_engineering'})
            if path in ('/', '/ui', '/client.js'):
                name = 'client.js' if path == '/client.js' else 'client.html'
                raw = (Path(__file__).parent / name).read_bytes()
                self.send_response(200); self.send_header('Content-Type', 'text/javascript; charset=utf-8' if name.endswith('.js') else 'text/html; charset=utf-8')
                self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'")
                self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)
                return
            self.send(404, {'error': '接口不存在'})
        def do_POST(self):
            if urlsplit(self.path).path != '/invocations': return self.send(404, {'error': '接口不存在'})
            if app_token and not hmac.compare_digest(self.headers.get('X-Embedded-App-Key', ''), app_token): return self.send(401, {'error': '应用认证失败'})
            # Gateway mode relies on platform IAM/API-Key/OAuth validation, never a payload field.
            if self.headers.get('Sec-Fetch-Site') == 'cross-site': return self.send(403, {'error': '拒绝跨站浏览器调用'})
            try:
                self.connection.settimeout(30)
                media = self.headers.get('Content-Type', '').split(';')[0].strip().lower()
                if media != 'application/json': raise ValueError('Content-Type必须为application/json；实际为' + media[:80])
                lengths = self.headers.get_all('Content-Length', [])
                transfers = self.headers.get_all('Transfer-Encoding', [])
                if len(lengths) > 1 or len(transfers) > 1 or (lengths and transfers): raise ValueError('请求长度头冲突')
                if transfers:
                    if transfers[0].strip().lower() != 'chunked': raise ValueError('不支持此Transfer-Encoding')
                    parts = []; total = 0
                    while True:
                        line = self.rfile.readline(1025)
                        if len(line) > 1024 or not line.endswith(b'\r\n'): raise ValueError('分块长度行无效')
                        token = line[:-2].split(b';', 1)[0]
                        if not re.fullmatch(b'[0-9a-fA-F]{1,8}', token): raise ValueError('分块长度无效')
                        size = int(token, 16)
                        if not size:
                            trailer_size = 0
                            while True:
                                trailer = self.rfile.readline(1025); trailer_size += len(trailer)
                                if not trailer.endswith(b'\r\n') or trailer_size > 8192: raise ValueError('分块尾部无效')
                                if trailer == b'\r\n': break
                            break
                        total += size
                        if total > 200_000: raise ValueError('JSON请求体超过200KB')
                        part = self.rfile.read(size)
                        if len(part) != size or self.rfile.read(2) != b'\r\n': raise ValueError('分块数据不完整')
                        parts.append(part)
                    raw = b''.join(parts)
                else:
                    if not lengths: raise ValueError('缺少Content-Length或Transfer-Encoding: chunked')
                    if not re.fullmatch(r'[0-9]+', lengths[0]): raise ValueError('Content-Length无效')
                    size = int(lengths[0])
                    if not 0 < size <= 200_000: raise ValueError('JSON请求体须为1至200000字节')
                    raw = self.rfile.read(size)
                    if len(raw) != size: raise ValueError('请求体不完整')
                session = self.headers.get('X-Hw-Agentarts-Session-Id')
                result = kernel.invoke(session, json.loads(raw))
                self.send(200, result)
            except FileNotFoundError: self.send(404, {'error': '当前会话中不存在该项目或运行'})
            except (ValueError, TypeError, KeyError) as exc: self.send(400, {'error': str(exc)[:300] if type(exc) is ValueError else '请求结构不正确'})
            except Exception: self.send(500, {'error': '执行或持久化失败，未报告成功；请查询状态后再操作'})
    return ThreadingHTTPServer((host, port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preview', action='store_true')
    parser.add_argument('--config', type=Path)
    args = parser.parse_args()
    if args.config:
        values = json.loads(args.config.read_text(encoding='utf-8'))
        for key, value in values.items():
            if key.startswith('CLOUD_') and isinstance(value, str): os.environ[key] = value
    state = os.environ.get('CLOUD_STATE_DIR')
    if not state and not args.preview: raise ValueError('需要CLOUD_STATE_DIR，且须指向控制台配置的会话存储挂载目录；不静默使用临时磁盘')
    state = Path(state) if state else ROOT / 'runtime/agentarts-preview/state'
    if not args.preview:
        mount = Path(os.environ.get('CLOUD_STORAGE_MOUNT', '/home/session')).resolve()
        mounts = Path('/proc/self/mountinfo')
        listed = mounts.is_file() and any(line.split()[4].replace('\\040', ' ') == str(mount) for line in mounts.read_text().splitlines() if len(line.split()) > 4)
        if not (mount.is_dir() and (os.path.ismount(mount) or listed) and state.resolve().is_relative_to(mount)):
            raise ValueError('未检测到配置的会话存储挂载点，停止启动以免把项目写入临时磁盘')
    model = configured()
    scratch = Path(tempfile.mkdtemp(prefix='embedded-agent-cloud-'))
    kernel = Kernel(ROOT, state, scratch, ModelDecider(model) if model else None)
    server = make_server(kernel, '127.0.0.1' if args.preview else '0.0.0.0', int(os.environ.get('CLOUD_PORT', '8786' if args.preview else '8080')),
                         trust_gateway=not args.preview and os.environ.get('CLOUD_TRUST_GATEWAY') == '1', app_token=os.environ.get('CLOUD_APP_TOKEN'))
    print('AgentArts适配入口就绪；模型' + ('已配置，未验证联通' if model else '未配置') + '；本地工作台未变更', flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally:
        server.server_close()
        if scratch.is_relative_to(Path(tempfile.gettempdir()).resolve()): shutil.rmtree(scratch)


if __name__ == '__main__': main()
