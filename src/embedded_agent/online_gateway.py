"""Invite-only BYOK web gateway. No shared keys or untrusted code execution.

Runs the existing engine in a separate loopback backend/root per browser session.
Public use requires HTTPS termination and a deployment owner supplied access code.
"""
import argparse
import base64
from copy import deepcopy
import hmac
import http.client
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import shutil
import tempfile
import threading
import time
from urllib.parse import urlsplit
from .local_model import LocalSettings, Budget, ENDPOINT

ONLINE_OPERATIONS=frozenset(('analysis','confirm','select','supplement','implementation',
    'mcu_implementation','implementation_scope','firmware_implementation',
    'design_plan','design_research','design_evaluate','design_recommend','design_accept',
    'power_estimate','proceed_estimated_design','selection_check','continue_selection',
    'start_draft','draft_artifacts','draft_edit','draft_patch','product_documents','execute'))
READS=frozenset(('search_documents','read_document_page','read_parameter','record_parameter','record_fact'))


def check_route(method, parts):
    if parts[0] in ('hardware','training'):
        raise ValueError('在线服务不访问服务器硬件或执行训练程序')
    if method=='POST':
        if len(parts)==3 and parts[0]=='projects' and parts[2] not in ONLINE_OPERATIONS | {'chat'}:
            raise ValueError('此操作需要本机工具或隔离执行器，在线服务未执行')
        if parts[:2]==['knowledge','web']:
            raise ValueError('当前在线部署未配置受控联网资料执行器，未执行')


class SessionSettings(LocalSettings):
    def __init__(self, root):
        self.folder=Path(root)/'runtime/local-model';self.folder.mkdir(parents=True,exist_ok=True)
        self.file=self.folder/'settings.json'
        self.budget=Budget(self.folder/'usage.sqlite3')
        self._config={'model':'deepseek-flash','enabled':False}

    def read(self):return deepcopy(self._config)
    def encode_key(self, value):return value
    def decode_key(self, value):return value
    def write_config(self, data):self._config=deepcopy(data)

    def save(self,payload):
        # Do not allow arbitrary user endpoints to reach internal/cloud metadata.
        # Additional compatible providers require an operator-reviewed adapter.
        if payload.get('endpoint',self.read().get('endpoint',ENDPOINT))!=ENDPOINT:
            raise ValueError('此在线部署仅允许DeepSeek官方API；自定义地址需部署者审核后接入')
        return super().save(payload)

    def public(self):
        return dict(super().public(),online=True,secret_storage='服务会话内存；退出、到期或重启即清除',
                    budget_scope='当前访客会话；不是服务商账户全局额度',
                    session_lifetime_seconds=28800,
                    execution_scope='analysis_chat_source_documents_only; no code execution, hardware or Keil')

    def clear(self):self._config={'model':'deepseek-flash','enabled':False}


class Sessions:
    def __init__(self, source, state, *, max_sessions=8, ttl=28800):
        self.source=Path(source).resolve();self.state=Path(state).resolve();self.state.mkdir(parents=True,exist_ok=True)
        self.max_sessions=max_sessions;self.ttl=ttl;self.lock=threading.RLock();self.items={}
        self.stopping=threading.Event()
        self.reaper=threading.Thread(target=self._reap,daemon=True);self.reaper.start()

    def _reap(self):
        while not self.stopping.wait(5):
            with self.lock:self.expire()

    def new(self):
        from .server import make_server
        with self.lock:
            self.expire()
            if len(self.items)>=self.max_sessions:raise ValueError('当前访客会话已满，请稍后重试')
            tmp=tempfile.TemporaryDirectory(prefix='visitor-',dir=self.state)
            root=Path(tmp.name).resolve()
            if root.parent!=self.state:raise ValueError('会话目录异常')
            try:
                (root/'knowledge').mkdir()
                # Only authored general cards, never local projects or downloads.
                catalog=json.loads((self.source/'knowledge/index.json').read_text(encoding='utf-8'))
                catalog['cards']=[c for c in catalog.get('cards',[]) if c.get('scope')=='general' and c.get('source_kind')=='authored_method']
                (root/'knowledge/index.json').write_text(json.dumps(catalog,ensure_ascii=False),encoding='utf-8')
                if (self.source/'docs').is_dir():shutil.copytree(self.source/'docs',root/'docs',ignore=shutil.ignore_patterns('*.zip','*.pdf','*.docx'))
                settings=SessionSettings(root)
                backend=make_server(root,0,settings_factory=lambda _:settings,online=True)
                thread=threading.Thread(target=backend.serve_forever,daemon=True);thread.start()
                key=secrets.token_urlsafe(32)
                self.items[key]={'backend':backend,'thread':thread,'settings':settings,'temporary':tmp,'created':time.monotonic(),'active':0}
                return key,self.items[key]
            except Exception:
                tmp.cleanup();raise

    def acquire(self, key):
        with self.lock:
            item=self.items.get(key)
            if item and time.monotonic()-item['created']<self.ttl:
                item['active']+=1;return item
            return None

    def release(self, item):
        with self.lock:item['active']-=1

    def discard(self,key):
        with self.lock:
            item=self.items.get(key)
            if not item:return
            if item['active']:raise ValueError('当前请求仍在执行，请等待完成后退出')
            self.items.pop(key)
            item['settings'].clear()
            item['backend'].shutdown();item['backend'].server_close();item['thread'].join(timeout=2)
            item['temporary'].cleanup()

    def expire(self):
        for key,item in list(self.items.items()):
            if not item['active'] and time.monotonic()-item['created']>=self.ttl:self.discard(key)

    def close(self):
        self.stopping.set();self.reaper.join(timeout=6)
        for key in list(self.items):self.discard(key)


def make_gateway(source,state,*,public_url,access_code,host='127.0.0.1',port=0,max_sessions=8):
    public=urlsplit(public_url)
    local=public.hostname in ('127.0.0.1','localhost')
    if (public.scheme!='https' and not (local and public.scheme=='http')) or not public.netloc or public.path not in ('','/') or public.query or public.fragment or public.username or public.password:
        raise ValueError('需填写完整HTTPS站点来源；HTTP仅允许本机预览')
    if not isinstance(access_code,str) or len(access_code)<16:raise ValueError('部署访问口令至少16字符')
    origin=public.scheme+'://'+public.netloc
    cookie_name='embedded_visitor' if local else '__Host-embedded_visitor'
    sessions=Sessions(source,state,max_sessions=max_sessions)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass

        def reply(self,status,value,headers=()):
            data=json.dumps(value,ensure_ascii=False).encode('utf-8');self.send_response(status)
            for key,val in headers:self.send_header(key,val)
            self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(data)))
            self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(data)

        def handle_api(self):
            item=None
            try:
                if self.headers.get('Host')!=public.netloc:return self.reply(400,{'error':'站点来源不匹配'})
                if self.headers.get('Origin') not in (None,origin) or self.headers.get('Sec-Fetch-Site')=='cross-site':return self.reply(403,{'error':'不允许跨站请求'})
                try:
                    auth=self.headers.get('Authorization','')
                    decoded=base64.b64decode(auth[6:],validate=True).decode('utf-8') if auth.startswith('Basic ') else ''
                    password=decoded.split(':',1)[1] if ':' in decoded else ''
                except (ValueError,UnicodeError):password=''
                if not hmac.compare_digest(password.encode('utf-8'),access_code.encode('utf-8')):
                    return self.reply(401,{'error':'请输入部署者提供的访问口令（用户名可任意填写）'},[('WWW-Authenticate','Basic realm="Embedded workbench", charset="UTF-8"')])
                self.connection.settimeout(120)
                if self.headers.get('Transfer-Encoding'):return self.reply(400,{'error':'不接受分块请求体'})
                size=int(self.headers.get('Content-Length','0'))
                if size<0 or size>200000:return self.reply(413,{'error':'请求过大'})
                if self.command=='POST' and (size==0 or self.headers.get('Content-Type','').split(';')[0]!='application/json'):
                    return self.reply(400,{'error':'需要JSON请求'})
                body=self.rfile.read(size) if size else b''
                if self.command=='POST':
                    payload=json.loads(body)
                    if not isinstance(payload,dict):return self.reply(400,{'error':'需要JSON对象'})
                else:payload={}
                cookie=SimpleCookie();cookie.load(self.headers.get('Cookie',''))
                key=cookie[cookie_name].value if cookie_name in cookie else ''
                if self.path=='/session/logout' and self.command=='POST':
                    sessions.discard(key)
                    return self.reply(200,{'logged_out':True},[('Set-Cookie',f'{cookie_name}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0'+('' if local else '; Secure'))])
                item=sessions.acquire(key)
                created=False
                if item is None:
                    if self.command!='GET' or self.path not in ('/','/index.html'):
                        return self.reply(401,{'error':'会话已失效，请刷新首页并重新填写自己的API'})
                    key,_=sessions.new();item=sessions.acquire(key);created=True
                parts=urlsplit(self.path).path.strip('/').split('/')
                if '?' in self.path or '%' in self.path or '..' in self.path:return self.reply(400,{'error':'不支持此路径'})
                check_route(self.command,parts)
                if self.command=='POST' and parts==['projects']:
                    folder=Path(item['temporary'].name)/'runtime/projects'
                    if len(list(folder.glob('*.json')))>=30:return self.reply(429,{'error':'当前会话最多30个项目，请先下载并结束会话'})
                if self.command=='POST' and parts==['knowledge','web','settings']:return self.reply(400,{'error':'在线部署未配置联网资料执行器'})
                if self.command=='POST' and len(parts)==3 and parts[0]=='runs' and parts[2]=='decisions':
                    action=payload.get('decision',{}).get('action')
                    if action not in ONLINE_OPERATIONS | READS | {'ask','finish'}:return self.reply(403,{'error':'此在线服务不执行生成代码或访问硬件'})
                backend=item['backend'];host_header=f'127.0.0.1:{backend.server_port}'
                connection=http.client.HTTPConnection('127.0.0.1',backend.server_port,timeout=120)
                try:
                    connection.request(self.command,self.path,body=body if self.command=='POST' else None,headers={'Host':host_header,'Origin':'http://'+host_header,'Content-Type':'application/json','Connection':'close'})
                    response=connection.getresponse();raw=response.read(16*1024*1024+1)
                    if len(raw)>16*1024*1024:return self.reply(413,{'error':'导出内容过大'})
                    self.send_response(response.status)
                    for name,value in response.getheaders():
                        if name.lower() in ('content-type','content-security-policy','content-disposition','x-content-type-options'):self.send_header(name,value)
                    self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(raw)))
                    if created:self.send_header('Set-Cookie',f'{cookie_name}={key}; Path=/; HttpOnly; SameSite=Strict; Max-Age=28800'+('' if local else '; Secure'))
                    self.end_headers();self.wfile.write(raw)
                finally:connection.close()
            except (ValueError,KeyError):self.reply(400,{'error':'请求无效或会话不可用'})
            except Exception as exc:
                # Diagnostic category only, never credentials, paths or bodies.
                self.server.last_error_category=type(exc).__name__
                self.reply(503,{'error':'在线服务暂不可用，未报告执行成功'})
            finally:
                if item is not None:sessions.release(item)

        do_GET=handle_api
        do_POST=handle_api
    server=ThreadingHTTPServer((host,port),Handler);server.sessions=sessions
    return server


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[2]);parser.add_argument('--port',type=int,default=8080);parser.add_argument('--host',default='127.0.0.1');args=parser.parse_args()
    server=make_gateway(args.root,args.root/'runtime/online-sessions',public_url=os.environ.get('PUBLIC_URL',''),access_code=os.environ.get('ONLINE_ACCESS_CODE',''),host=args.host,port=args.port)
    print('在线工作台已启动；API仅在访客服务会话内存保存，未连接本机编译/硬件执行器。',flush=True)
    try:server.serve_forever()
    finally:server.server_close();server.sessions.close()

if __name__=='__main__':main()
