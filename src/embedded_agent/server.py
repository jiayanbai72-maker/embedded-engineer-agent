"""Single-process loopback-only JSON API. No external exposure or model calls."""
import argparse
import json
import threading
import os
import time
from contextlib import nullcontext
from urllib.parse import urlsplit
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from .service import EngineeringService
from .control import DecisionController
from .readiness import assess, capabilities
from .autonomy import AutonomousRunner, ModelDecider
from .model import configured_model
from .local_model import LocalSettings, BudgetModel, PRICES, ENDPOINT
from . import hardware


def make_server(root, port=8765, *, decision_provider=None, settings_factory=None, online=False):
    service = EngineeringService(root)
    service.settings_factory=settings_factory
    if online:
        from .online_gateway import ONLINE_OPERATIONS
        service.online_allowed_operations=ONLINE_OPERATIONS
        service.app.online_mode=True
    control = DecisionController(service)
    settings = settings_factory(root) if settings_factory else LocalSettings(root)
    from .conversation import Conversations
    conversations=Conversations(root)
    operation_lock = threading.RLock()
    progress_lock = threading.Lock()
    progress_states = {}
    def publish(run_id, **event):
        with progress_lock:
            prior = progress_states.get(run_id, {})
            now = time.time()
            started = prior.get('started_at', now) if prior.get('busy') else now
            state = dict(prior, **event, started_at=started, updated_at=now, sequence=prior.get('sequence', 0)+1)
            history = prior.get('history', [])[-11:] + [{k: state.get(k) for k in ('phase', 'action', 'detail', 'rationale', 'updated_at')}]
            state['history'] = history
            progress_states[run_id] = state
    # Explicit opt-in only; existing model configuration alone never starts calls.
    model = configured_model() if not online and decision_provider is None and os.environ.get('EMBEDDED_AGENT_AUTONOMY') == '1' else None
    runner = AutonomousRunner(control, decision_provider if decision_provider is not None else ModelDecider(model) if model else None)
    class Handler(BaseHTTPRequestHandler):
        def static(self, name, content_type):
            raw = (Path(__file__).parent / 'web' / name).read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *args):
            pass  # Do not log descriptions or credentials.

        def reply(self, code, value):
            raw = json.dumps(value, ensure_ascii=False).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(raw)

        def handle_request(self):
            parts = self.path.strip('/').split('/')
            progress_request = self.command == 'GET' and len(parts) == 3 and parts[0] == 'runs' and parts[2] == 'progress'
            # Polling remains available during a slow model/tool call. Other
            # operations remain serialized for the existing JSON project store.
            with (nullcontext() if progress_request else operation_lock):
                self.handle_locked_request()

        def handle_locked_request(self):
            try:
                if self.headers.get('Host') not in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'):
                    raise ValueError('Host 不匹配')
                origin = self.headers.get('Origin')
                if origin and origin != 'http://' + self.headers.get('Host'):
                    raise ValueError('不接受浏览器跨来源请求')
                if self.headers.get('Sec-Fetch-Site') == 'cross-site':
                    raise ValueError('不接受跨站请求')
                parts = self.path.strip('/').split('/')
                if online:
                    from .online_gateway import check_route
                    check_route(self.command,parts)
                if self.command == 'GET':
                    if online and len(parts)==3 and parts[0]=='projects' and parts[2]=='source-download':
                        # Export an explicitly unverified snapshot without
                        # manufacturing a passed build or delivery assessment.
                        raw=service.archive(service.app.store.load(parts[1]))
                        self.send_response(200);self.send_header('Content-Type','application/zip')
                        self.send_header('Content-Disposition','attachment; filename="unverified-project-draft.zip"')
                        self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.end_headers()
                        return self.wfile.write(raw)
                    if len(parts) == 3 and parts[0] == 'runs' and parts[2] == 'progress':
                        control.path(parts[1])
                        with progress_lock:
                            state = dict(progress_states.get(parts[1], {'phase': 'idle', 'busy': False, 'detail': '当前没有正在执行的请求', 'sequence': 0}))
                        state['elapsed_seconds'] = round(max(0, time.time()-state['started_at']), 1) if state.get('busy') else 0
                        return self.reply(200, state)
                    if parts == ['hardware', 'devices']:
                        return self.reply(200, dict(hardware.discover(service.root), usb=hardware.usb_inventory()))
                    if parts == ['training','status']:
                        from .offline_curriculum import status
                        return self.reply(200,status(service.root))
                    if parts == ['capabilities']:
                        report = capabilities(service.app)
                        configured = settings.public()
                        for item in report['items']:
                            if item['id'] == 'autonomous_decision':
                                item.update(status='configured_unverified' if configured['enabled'] else 'not_connected', detail='在模型设置中填写密钥；每日10元保守预算，实际联通以调用结果为准')
                        return self.reply(200, report)
                    if parts == ['model', 'settings']:
                        return self.reply(200, settings.public())
                    if len(parts)==3 and parts[0]=='projects' and parts[2]=='chat':
                        service.get(parts[1])
                        return self.reply(200,{'messages':conversations.history(parts[1])})
                    if len(parts) == 3 and parts[0] == 'projects' and parts[2] == 'readiness':
                        return self.reply(200, assess(service.get(parts[1])))
                    if len(parts) == 3 and parts[0] == 'projects' and parts[2] == 'test_suites':
                        from .test_suites import available
                        service.get(parts[1])
                        return self.reply(200, {'suites':available(service.root,parts[1])})
                    if parts == ['knowledge','status']:
                        return self.reply(200,service.app.documents.status())
                    if parts == ['knowledge','web','settings']:
                        return self.reply(200,service.web.settings())
                    if len(parts)==3 and parts[0]=='projects' and parts[2]=='web_research':
                        service.get(parts[1])
                        return self.reply(200,service.web.history(parts[1]))
                    if parts == ['knowledge','parameters']:
                        return self.reply(200,{'parameters':service.app.parameters.list(),'facts':service.app.parameters.facts()})
                    if len(parts)==4 and parts[:2]==['knowledge','documents'] and parts[3]=='file':
                        doc=service.app.documents.document(parts[2])
                        file=service.app.documents.safe(doc['file'])
                        raw=file.read_bytes()
                        self.send_response(200)
                        self.send_header('Content-Type','application/pdf' if file.suffix.lower()=='.pdf' else 'text/plain; charset=utf-8')
                        self.send_header('Content-Length',str(len(raw)))
                        self.send_header('X-Content-Type-Options','nosniff')
                        self.send_header('Content-Security-Policy',"sandbox; default-src 'none'")
                        self.end_headers()
                        return self.wfile.write(raw)
                    assets = {'': ('index.html', 'text/html; charset=utf-8'),
                              'app.js': ('app.js', 'text/javascript; charset=utf-8'),
                              'style.css': ('style.css', 'text/css; charset=utf-8')}
                    if self.path.strip('/') in assets:
                        return self.static(*assets[self.path.strip('/')])
                    if parts == ['projects']:
                        items = []
                        for path in sorted(service.app.store.root.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True):
                            project = service.get(path.stem)
                            items.append({k: project[k] for k in ('id', 'description', 'status', 'revision', 'stage')})
                        return self.reply(200, {'projects': items})
                    if parts == ['health']:
                        return self.reply(200, {'status': 'ok', 'mode': 'analyst_assisted', 'local_model_settings': True})
                    if len(parts) == 2 and parts[0] == 'runs':
                        return self.reply(200, control.context(parts[1]))
                    if len(parts) >= 2 and parts[0] == 'projects':
                        if len(parts) == 2:
                            return self.reply(200, service.get(parts[1]))
                        if len(parts) == 3 and parts[2] == 'runs':
                            service.get(parts[1])
                            return self.reply(200, {'runs': [r for p in sorted(control.root.glob('*.json'),key=lambda p:p.stat().st_mtime_ns) if (r := control.load(p.stem))['project_id'] == parts[1]]})
                        if len(parts) == 3 and parts[2] == 'download':
                            raw = service.download(parts[1])
                            self.send_response(200)
                            self.send_header('Content-Type', 'application/zip')
                            self.send_header('Content-Disposition', 'attachment; filename="project-documents.zip"')
                            self.send_header('Content-Length', str(len(raw)))
                            self.end_headers()
                            return self.wfile.write(raw)
                        if len(parts) == 3 and parts[2] == 'product-design':
                            from .product_documents import exports, fingerprint
                            project=service.app.store.load(parts[1]);document=project.artifacts.get('product_documents')
                            if not document or document.get('source_sha256')!=fingerprint(project):raise ValueError('详细设计尚未生成或需要更新')
                            raw=exports(document)['product-design/产品详细设计与制作说明.html'].encode('utf-8')
                            self.send_response(200)
                            self.send_header('Content-Type','text/html; charset=utf-8')
                            self.send_header('Content-Length',str(len(raw)))
                            self.send_header('X-Content-Type-Options','nosniff')
                            self.send_header('Content-Security-Policy',"sandbox allow-popups; default-src 'none'; style-src 'unsafe-inline'")
                            self.end_headers()
                            return self.wfile.write(raw)
                if self.command == 'POST':
                    if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                        raise ValueError('需要 application/json')
                    size = int(self.headers.get('Content-Length', '0'))
                    if not 0 < size <= 200_000:
                        raise ValueError('请求体为空或超过限制')
                    payload = json.loads(self.rfile.read(size))
                    if not isinstance(payload, dict):
                        raise ValueError('请求体必须为对象')
                    if parts == ['model', 'settings']:
                        return self.reply(200, settings.save(payload))
                    if len(parts)==3 and parts[0]=='projects' and parts[2]=='chat':
                        return self.reply(200,conversations.send(service.get(parts[1]),payload,settings.model()))
                    if parts == ['model', 'resume']:
                        if payload.get('confirmed') is not True: raise ValueError('需要明确保留全部预留费用后继续')
                        settings.budget.acknowledge_uncertainty()
                        return self.reply(200, settings.public())
                    if parts == ['model', 'test']:
                        selected = settings.model()
                        if selected is None: raise ValueError('请先保存并启用模型')
                        answer=selected.generate(role='connection_test', instruction='返回JSON对象 {"ok":true}', context={'test': 'connection_only'})
                        if answer.get('ok') is not True:raise ValueError('服务已响应，但未按约定返回ok=true；请检查模型的JSON兼容性')
                        return self.reply(200, dict(settings.public(), message='模型已返回有效JSON；本次测试也计入每日预算'))
                    if parts == ['knowledge','search']:
                        return self.reply(200,{'matches':service.app.documents.search(payload.get('query'),payload.get('limit',8),payload.get('document_id'))})
                    if parts == ['knowledge','web','settings']:
                        return self.reply(200,service.web.configure(payload))
                    if parts == ['knowledge','web','retry']:
                        project_id=payload.get('project_id');service.get(project_id)
                        return self.reply(200,service.web.retry_failed(project_id,payload.get('confirmed')))
                    if parts in (['knowledge','web','research'],['knowledge','web','fetch']):
                        project_id=payload.get('project_id');service.get(project_id)
                        if parts[-1]=='fetch':return self.reply(200,service.web.import_url(project_id,payload.get('url')))
                        return self.reply(200,service.web.autonomous_research(project_id,payload.get('query'),payload.get('missing_field')))
                    if parts == ['knowledge','page']:
                        return self.reply(200,service.app.documents.page(payload.get('document_id'),payload.get('page')))
                    if parts == ['knowledge','parameters']:
                        return self.reply(201,service.app.parameters.review(payload))
                    if parts == ['projects']:
                        return self.reply(201, service.create(payload.get('description')))
                    if parts == ['runs']:
                        return self.reply(201, control.create(payload.get('project_id'), payload.get('max_steps', 20), payload.get('max_repairs', 3),scope=payload.get('scope'),task=payload.get('task'),evidence_goal=payload.get('evidence_goal')))
                    if len(parts) == 3 and parts[0] == 'runs':
                        if parts[2] == 'reply':
                            return self.reply(200, control.reply(parts[1], payload.get('revision'), payload.get('message')))
                        if parts[2] == 'auto':
                            if decision_provider is None:
                                selected = settings.model()
                                if not settings.file.exists() and model:
                                    if model.endpoint != ENDPOINT or model.model not in PRICES:
                                        raise ValueError('测试期预算仅支持设置页中的DeepSeek官方模型，请在模型设置中接入')
                                    selected = BudgetModel(model.model, model._key, settings.budget)
                                runner.provider = ModelDecider(selected) if selected else None
                            return self.reply(200, runner.step(parts[1], progress=lambda **event: publish(parts[1], **event)))
                        if parts[2] == 'plan':
                            return self.reply(200, control.plan(parts[1], payload.get('revision'), payload.get('plan')))
                        if parts[2] == 'decisions':
                            return self.reply(200, control.submit(parts[1], payload.get('revision'), payload.get('decision')))
                        if parts[2] == 'tick':
                            return self.reply(200, control.tick(parts[1]))
                        if parts[2] == 'refresh':
                            return self.reply(200, control.refresh(parts[1], payload.get('revision')))
                    if len(parts) == 3 and parts[0] == 'projects':
                        return self.reply(200, service.update(parts[1], payload.get('revision'), parts[2], payload))
                return self.reply(404, {'error': '接口不存在'})
            except FileNotFoundError:
                self.reply(404, {'error': '项目不存在'})
            except (ValueError, KeyError, TypeError) as exc:
                message = str(exc)[:200] if isinstance(exc, ValueError) and not isinstance(exc, json.JSONDecodeError) else '请求格式不正确，请检查JSON字段'
                self.reply(400, {'error': message})
            except Exception:
                self.reply(500, {'error': '执行失败，未报告成功'})

        do_GET = handle_request
        do_POST = handle_request

    server=ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.session_settings=settings
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).absolute().parents[2])
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    server = make_server(args.root, args.port)
    print(f'本地服务：http://127.0.0.1:{server.server_port}；模型可在页面手动配置，保存不发起调用', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
