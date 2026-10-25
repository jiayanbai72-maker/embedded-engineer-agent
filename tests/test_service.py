import json
import threading
import urllib.request
import unittest
import io
from zipfile import ZipFile
import test_architecture
from embedded_agent.service import EngineeringService
from embedded_agent.server import make_server


class ServiceTests(unittest.TestCase):
    setUp = test_architecture.ArchitectureTests.setUp
    tearDown = test_architecture.ArchitectureTests.tearDown

    def analysis(self):
        return json.loads((test_architecture.ROOT / 'examples/analyst-door-monitor.json').read_text(encoding='utf-8'))

    def test_confirm_selection_download_restart_and_invalidation(self):
        service = EngineeringService(self.root)
        p = service.create('电池供电，检测门窗开闭，手机查看；只交付设计文档')
        with self.assertRaises(ValueError): service.update(p['id'], 0, 'execute', {})
        p = service.update(p['id'], p['revision'], 'analysis', self.analysis())
        p = service.update(p['id'], p['revision'], 'confirm', {'confirmed': True})
        p = EngineeringService(self.root).get(p['id'])
        self.assertEqual(p['status'], 'awaiting_selection')
        p = service.update(p['id'], p['revision'], 'select', {'candidate_id': 'PLAN-NEAR'})
        p = service.update(p['id'], p['revision'], 'execute', {})
        restarted = EngineeringService(self.root)
        raw = restarted.download(p['id'])
        with ZipFile(io.BytesIO(raw)) as archive:
            self.assertIn('decision.json', archive.namelist())
            self.assertIn('尚未执行', archive.read('README.md').decode())
        self.assertEqual(p['verification']['hardware'], 'not_run')
        p = restarted.update(p['id'], p['revision'], 'supplement', {'message': '改为远程查看'})
        self.assertEqual(p['status'], 'awaiting_analysis')
        with self.assertRaises(ValueError): restarted.download(p['id'])

    def test_revision_and_blocking_questions(self):
        service = EngineeringService(self.root)
        p = service.create('测试')
        data = self.analysis()
        data['requirements']['questions'][0]['blocking'] = True
        p = service.update(p['id'], p['revision'], 'analysis', data)
        with self.assertRaises(ValueError): service.update(p['id'], 0, 'confirm', {'confirmed': True})
        with self.assertRaises(ValueError): service.update(p['id'], p['revision'], 'confirm', {'confirmed': True})

    def test_real_http_and_server_restart(self):
        def start():
            server = make_server(self.root, 0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            return server, thread
        server, thread = start()
        def request(method, path, payload=None):
            body = None if payload is None else json.dumps(payload).encode()
            req = urllib.request.Request(f'http://127.0.0.1:{server.server_port}' + path, data=body,
                                         headers={'Content-Type': 'application/json'}, method=method)
            with urllib.request.urlopen(req, timeout=5) as response:
                raw = response.read()
                return raw if path.endswith('/download') else json.loads(raw)
        try:
            p = request('POST', '/projects', {'description': '电池门窗监测，手机查看，只交付文档'})
            url = '/projects/' + p['id']
            p = request('POST', url + '/analysis', dict(self.analysis(), revision=p['revision']))
            p = request('POST', url + '/confirm', {'revision': p['revision'], 'confirmed': True})
            server.shutdown(); server.server_close(); thread.join()
            server, thread = start()
            p = request('GET', url)
            self.assertEqual(p['status'], 'awaiting_selection')
            p = request('POST', url + '/select', {'revision': p['revision'], 'candidate_id': 'PLAN-REMOTE'})
            p = request('POST', url + '/execute', {'revision': p['revision']})
            raw = request('GET', url + '/download')
            self.assertTrue(raw.startswith(b'PK'))
        finally:
            server.shutdown(); server.server_close(); thread.join()
