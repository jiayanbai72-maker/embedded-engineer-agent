import json
import threading
import unittest
import urllib.request
import urllib.error
import test_architecture
from embedded_agent.server import make_server


class WebTests(unittest.TestCase):
    setUp = test_architecture.ArchitectureTests.setUp
    tearDown = test_architecture.ArchitectureTests.tearDown

    def test_assets_same_origin_persistence_and_cross_origin_rejection(self):
        def start():
            server = make_server(self.root, 0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            return server, thread
        server, thread = start()
        def request(path, payload=None, origin=None):
            headers = {'Content-Type': 'application/json'}
            if origin: headers['Origin'] = origin
            req = urllib.request.Request(f'http://127.0.0.1:{server.server_port}'+path,
                                         data=None if payload is None else json.dumps(payload).encode(), headers=headers)
            return urllib.request.urlopen(req, timeout=5)
        try:
            with request('/') as response:
                self.assertIn('分析者入口', response.read().decode())
                self.assertIn("frame-ancestors 'none'", response.headers['Content-Security-Policy'])
            for path in ('/app.js','/style.css'):
                with request(path) as response: self.assertTrue(response.read())
            origin = f'http://127.0.0.1:{server.server_port}'
            with request('/projects', {'description': '网页创建的项目'}, origin) as response: p=json.loads(response.read())
            with request('/projects') as response: self.assertEqual(json.loads(response.read())['projects'][0]['id'],p['id'])
            with request('/projects/'+p['id']+'/runs') as response: self.assertEqual(json.loads(response.read())['runs'],[])
            with self.assertRaises(urllib.error.HTTPError) as rejected:
                request('/projects', {'description': '不能创建'}, 'https://untrusted.example')
            self.assertEqual(rejected.exception.code,400)
            server.shutdown(); server.server_close(); thread.join()
            server,thread=start()
            with request('/projects/'+p['id']) as response: self.assertEqual(json.loads(response.read())['description'],'网页创建的项目')
        finally:
            server.shutdown(); server.server_close(); thread.join()
