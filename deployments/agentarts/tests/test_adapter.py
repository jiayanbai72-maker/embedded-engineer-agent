import base64
import importlib.util
import io
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch
from deployments.agentarts.app import ROOT, Kernel, make_server
from deployments.agentarts.model_adapter import PlatformModel


class FixtureProvider:
    """Contract fixture only; never claims a real model result."""
    def decide(self, context):
        status = context['project']['status']
        if status == 'awaiting_analysis':
            spec = importlib.util.spec_from_file_location('cloud_example', ROOT / 'examples/run_full_flow.py')
            module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
            arguments = module.authored_analysis()
            arguments['decision']['actions'] = ['export_documents']
            action = 'analysis'
        else: action, arguments = ('finish' if status == 'documents_delivered' else 'execute'), {}
        return {'kind': 'decision', 'action': action, 'arguments': arguments, 'rationale': 'test_fixture_not_model', 'expected': 'persist actual result'}


class CloudTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.folder = Path(self.temp.name)
        self.kernel = Kernel(ROOT, self.folder / 'state', self.folder / 'scratch')
        # Test a clean minimal image, not the 600MB local reference library.
        source = self.folder / 'source'; (source / 'knowledge').mkdir(parents=True)
        (source / 'knowledge/index.json').write_bytes((ROOT / 'knowledge/index.json').read_bytes())
        self.kernel.source = source
    def tearDown(self): self.temp.cleanup()

    def test_no_model_is_not_fake_analysis_and_restart_restores(self):
        p = self.kernel.invoke('session-a', {'message': '监测环境，先做文档'})
        self.assertEqual(p['status'], 'model_not_connected')
        self.assertEqual(p['project']['status'], 'awaiting_analysis')
        self.assertFalse(p['model_connected'])
        new = Kernel(self.kernel.source, self.folder / 'state', self.folder / 'new-scratch')
        restored = new.invoke('session-a', {'action': 'status', 'run_id': p['run']['id']})
        self.assertEqual(restored['project'], p['project'])
        with self.assertRaises(FileNotFoundError): new.invoke('session-b', {'action': 'status', 'run_id': p['run']['id']})

    def test_partial_checkpoint_falls_back_without_overwriting(self):
        p = self.kernel.invoke('session-a', {'message': '测试快照'})
        folder = next((self.folder / 'state').iterdir())
        (folder / 'checkpoint-99999999999999999999-broken.json').write_text('{broken', encoding='utf-8')
        new = Kernel(self.kernel.source, self.folder / 'state', self.folder / 'new-scratch')
        restored = new.invoke('session-a', {'action': 'status', 'run_id': p['run']['id']})
        self.assertEqual(restored['project']['id'], p['project']['id'])

    def test_full_document_delivery_with_explicit_fixture(self):
        self.kernel.provider = FixtureProvider()
        p = self.kernel.invoke('session-a', {'message': '主机行为设计文档，不运行代码'})
        self.assertEqual(p['project']['status'], 'needs_input')
        rid = p['run']['id']
        p = self.kernel.invoke('session-a', {'action': 'confirm', 'run_id': rid, 'project_revision': p['project']['revision']})
        self.assertEqual(p['project']['status'], 'awaiting_selection')
        p = self.kernel.invoke('session-a', {'action': 'select', 'run_id': rid, 'candidate_id': 'PLAN-1', 'project_revision': p['project']['revision']})
        self.assertEqual(p['project']['status'], 'documents_delivered')
        package = self.kernel.invoke('session-a', {'action': 'download', 'run_id': rid})
        self.assertTrue(base64.b64decode(package['base64']).startswith(b'PK'))
        self.assertEqual(p['project']['verification']['hardware'], 'not_run')

    def test_cloud_never_exposes_host_keil_or_usb(self):
        p = self.kernel.invoke('session-a', {'message': '测试权限'})
        _, controller, *_ = self.kernel.session('session-a')
        context = controller.context(p['run']['id'])
        self.assertNotIn('discover_hardware', context['allowed_actions'])
        for action in ('implementation', 'keil_build', 'hardware_capture', 'shell'):
            with self.assertRaises(ValueError): controller.submit(p['run']['id'], p['run']['revision'], {'action': action})

    def test_http_session_required_and_application_auth(self):
        server = make_server(self.kernel, port=0, app_token='test-app-token')
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        url = 'http://127.0.0.1:' + str(server.server_port)
        try:
            with urlopen(url + '/ping') as response: self.assertEqual(response.status, 200)
            for headers, expected in [({}, 401), ({'X-Embedded-App-Key': 'test-app-token'}, 400)]:
                request = Request(url + '/invocations', data=b'{"message":"test"}', headers={'Content-Type': 'application/json', **headers})
                with self.assertRaises(HTTPError) as error: urlopen(request)
                self.assertEqual(error.exception.code, expected)
            request = Request(url + '/invocations', data=b'{"message":"test"}', headers={'Content-Type': 'application/json', 'X-Embedded-App-Key': 'test-app-token', 'X-Hw-Agentarts-Session-Id': 'session-a'})
            with urlopen(request) as response: self.assertEqual(json.load(response)['status'], 'model_not_connected')
        finally: server.shutdown(); server.server_close(); thread.join()

    def test_model_proxy_custom_header_not_bearer_and_no_key_in_payload(self):
        captured = []
        class Response(io.BytesIO): pass
        class Opener:
            def open(self, request, **kwargs):
                captured.append(request)
                return Response(json.dumps({'choices': [{'finish_reason': 'stop', 'message': {'content': '{"kind":"pause","reason":"test"}'}}]}).encode())
        model = PlatformModel('https://example.invalid/inference/v1/chat/completions', 'fixture-model', 'secret-fixture', 'X-Model-Key', '')
        with patch('deployments.agentarts.model_adapter.build_opener', return_value=Opener()):
            self.assertEqual(model.generate(role='test', instruction='test', context={})['kind'], 'pause')
        self.assertEqual(captured[0].get_header('X-model-key'), 'secret-fixture')
        self.assertNotIn(b'secret-fixture', captured[0].data)

    def test_gateway_chunked_query_and_limits(self):
        server = make_server(self.kernel, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        def post(body, headers, chunked=False):
            conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
            try:
                conn.request('POST', '/invocations?endpoint=Latest', body=body,
                             headers={'Content-Type': 'Application/JSON; charset=utf-8',
                                      'X-Hw-Agentarts-Session-Id': 'gateway-test', **headers}, encode_chunked=chunked)
                response = conn.getresponse()
                return response.status, json.loads(response.read())
            finally: conn.close()
        try:
            status, result = post(iter([b'{"message":', b'"gateway test"}']), {}, True)
            self.assertEqual(status, 200)
            self.assertEqual(result['status'], 'model_not_connected')
            status, _ = post(b'{"message":"fixed length"}', {})
            self.assertEqual(status, 200)
            self.assertEqual(post(iter([b'x' * 200001]), {}, True)[0], 400)
            self.assertEqual(post(iter([b'{}']), {'Content-Length': '2', 'Transfer-Encoding': 'chunked'}, True)[0], 400)
            self.assertEqual(post(b'{}', {'Content-Type': 'text/plain'})[0], 400)
        finally: server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__': unittest.main()
