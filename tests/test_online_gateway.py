import base64
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from embedded_agent.online_gateway import make_gateway

ROOT=Path(__file__).resolve().parents[1]


class OnlineGatewayTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.server=make_gateway(ROOT,Path(self.temp.name),public_url='http://localhost:12345',access_code='test-invite-password',port=0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.auth='Basic '+base64.b64encode(b'user:test-invite-password').decode()

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.server.sessions.close();self.temp.cleanup()

    def request(self,path,body=None,cookie=None,**extra):
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=10)
        headers={'Host':'localhost:12345','Authorization':self.auth}
        if cookie:headers['Cookie']=cookie
        if body is not None:headers['Content-Type']='application/json'
        headers.update(extra)
        try:
            connection.request('GET' if body is None else 'POST',path,body=None if body is None else json.dumps(body),headers=headers)
            r=connection.getresponse();return r.status,dict(r.getheaders()),r.read()
        finally:connection.close()

    def visitor(self):
        code,headers,_=self.request('/');self.assertEqual(code,200)
        cookie=headers['Set-Cookie'].split(';')[0]
        self.assertIn('HttpOnly',headers['Set-Cookie']);self.assertIn('SameSite=Strict',headers['Set-Cookie'])
        return cookie

    def test_auth_origin_host_and_expired_session(self):
        self.assertEqual(self.request('/',Authorization='')[0],401)
        self.assertEqual(len(self.server.sessions.items),0)
        self.assertEqual(self.request('/',Host='evil.example')[0],400)
        self.assertEqual(self.request('/',Origin='https://evil.example')[0],403)
        self.assertEqual(self.request('/model/settings')[0],401)

    def test_visitors_cannot_read_each_others_projects_or_keys(self):
        a=self.visitor();b=self.visitor()
        code,_,raw=self.request('/projects',{'description':'private project A'},a);self.assertEqual(code,201);p=json.loads(raw)
        self.assertEqual(self.request('/projects/'+p['id'],cookie=b)[0],404)
        self.assertEqual(self.request('/projects/'+p['id']+'/source-download',cookie=b)[0],404)
        raw=self.request('/projects',cookie=b)[2];self.assertEqual(json.loads(raw)['projects'],[])
        code,_,raw=self.request('/model/settings',{'model':'deepseek-flash','enabled':True,'api_key':'fake-session-secret-A'},a)
        self.assertEqual(code,200);self.assertNotIn(b'fake-session-secret-A',raw)
        self.assertFalse(json.loads(self.request('/model/settings',cookie=b)[2])['key_saved'])
        for file in Path(self.temp.name).rglob('*'):
            if file.is_file():self.assertNotIn(b'fake-session-secret-A',file.read_bytes())

    def test_clear_and_logout_do_not_call_provider(self):
        cookie=self.visitor()
        self.request('/model/settings',{'model':'deepseek-flash','enabled':True,'api_key':'fake-secret'},cookie)
        code,_,raw=self.request('/model/settings',{'clear_key':True},cookie)
        self.assertEqual(code,200);self.assertFalse(json.loads(raw)['enabled']);self.assertFalse(json.loads(raw)['key_saved'])
        item=next(iter(self.server.sessions.items.values()));folder=Path(item['temporary'].name)
        self.assertEqual(self.request('/session/logout',{},cookie)[0],200)
        self.assertFalse(folder.exists());self.assertEqual(len(self.server.sessions.items),0)
        self.assertEqual(self.request('/model/settings',cookie=cookie)[0],401)

    def test_cloud_does_not_execute_sources_or_server_hardware(self):
        cookie=self.visitor();p=json.loads(self.request('/projects',{'description':'test'},cookie)[2])
        for operation in ('build','test','draft_verify','mcu_build','mcu_test','firmware_build','keil_import','keil_edit','keil_build','hardware_bind','hardware_capture','draft_tests'):
            self.assertEqual(self.request('/projects/'+p['id']+'/'+operation,{'revision':p['revision']},cookie)[0],400,operation+': '+getattr(self.server,'last_error_category','no diagnostic'))
        self.assertEqual(self.request('/hardware/devices',cookie=cookie)[0],400)
        self.assertEqual(self.request('/training/status',cookie=cookie)[0],400)
        self.assertEqual(self.request('/model/settings',{'endpoint':'https://127.0.0.1/private','api_key':'secret'},cookie)[0],400)
        code,_,raw=self.request('/projects/'+p['id']+'/source-download',cookie=cookie)
        self.assertEqual(code,200);self.assertTrue(raw.startswith(b'PK'))
        self.assertEqual(json.loads(self.request('/projects/'+p['id'],cookie=cookie)[2])['status'],'awaiting_analysis')
        run=json.loads(self.request('/runs',{'project_id':p['id']},cookie)[2])
        ctx=json.loads(self.request('/runs/'+run['id'],cookie=cookie)[2])
        self.assertNotIn('discover_hardware',ctx['allowed_actions'])
        caps=json.loads(self.request('/capabilities',cookie=cookie)[2])
        self.assertEqual(next(c for c in caps['items'] if c['id']=='host_validation')['status'],'not_connected')

    def test_ttl_and_session_limit(self):
        self.server.sessions.max_sessions=1
        cookie=self.visitor()
        self.assertEqual(self.request('/')[0],400)
        item=next(iter(self.server.sessions.items.values()));item['created']-=self.server.sessions.ttl+1
        self.server.sessions.expire();self.assertFalse(item['settings'].read().get('encrypted_key'));self.assertIsNone(item['settings'].model())
        self.assertEqual(self.request('/model/settings',cookie=cookie)[0],401)


if __name__=='__main__':unittest.main()
