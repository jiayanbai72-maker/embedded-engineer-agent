"""Bounded public-source research. No search API key, paid API, or parameter approval."""
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urljoin, urlencode, urlunsplit
from uuid import UUID
import hashlib
import http.client
import ipaddress
import json
import socket
import ssl
import xml.etree.ElementTree as ET
import re
import subprocess
import sys
import threading

LOCK=threading.RLock()
DEFAULT_DOMAINS=['st.com','ti.com','nxp.com','microchip.com','espressif.com','arm.com','chipintelli.com','towerpro.com.tw']

def canonical(url):
    if not isinstance(url,str) or len(url)>3000 or any(ord(c)<33 for c in url):raise ValueError('资料URL无效')
    p=urlsplit(url)
    if p.scheme!='https' or not p.hostname or p.username or p.password or p.port not in (None,443):
        raise ValueError('只允许无凭据的公开HTTPS网址及443端口')
    host=p.hostname.encode('idna').decode('ascii').lower().rstrip('.')
    if not re.fullmatch(r'[a-z0-9.-]+',host) or '.' not in host:raise ValueError('域名无效')
    return urlunsplit(('https',host,p.path or '/',p.query,''))

def approved(url, domains):
    host=urlsplit(canonical(url)).hostname
    return any(host==d or host.endswith('.'+d) for d in domains)

def public_addresses(host):
    rows=socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)
    ips=list(dict.fromkeys(row[4][0] for row in rows))
    if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
        raise ValueError('禁止访问内网、回环、链路本地或非公开地址')
    return ips

def fetch_public(url,domains,max_bytes=8_000_000):
    """Pin each TLS connection to a checked IP; validate each redirect anew."""
    current=canonical(url)
    for _ in range(4):
        if not approved(current,domains):raise ValueError('来源或跳转域名不在允许列表中')
        p=urlsplit(current);ips=public_addresses(p.hostname)
        conn=http.client.HTTPSConnection(p.hostname,timeout=12,context=ssl.create_default_context())
        conn._create_connection=lambda address,timeout,source_address=None:socket.create_connection((ips[0],443),timeout,source_address)
        try:
            conn.request('GET',p.path+('?' + p.query if p.query else ''),headers={
                'User-Agent':'EmbeddedEngineerResearch/1.0','Accept':'text/html,application/pdf,application/rss+xml,application/xml,text/plain',
                'Accept-Encoding':'identity'})
            response=conn.getresponse()
            if response.status in (301,302,303,307,308):
                target=response.getheader('Location')
                if not target:raise ValueError('跳转缺少目标')
                current=canonical(urljoin(current,target));continue
            if response.status!=200:raise ValueError('公开资料请求返回HTTP '+str(response.status))
            length=response.getheader('Content-Length')
            if length and (not length.isdigit() or int(length)>max_bytes):raise ValueError('下载资料超过大小限制')
            if response.getheader('Content-Encoding','identity').lower() not in ('','identity'):raise ValueError('不接受压缩响应，避免解压超限')
            raw=response.read(max_bytes+1)
            if len(raw)>max_bytes:raise ValueError('下载资料超过大小限制')
            return {'url':current,'raw':raw,'mime':response.getheader('Content-Type','').split(';')[0].lower()}
        finally:conn.close()
    raise ValueError('来源跳转次数超过限制')

def atomic(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(path)

class OnlineResearch:
    def __init__(self,root,library):
        self.root=Path(root).resolve();self.library=library;self.folder=self.root/'runtime/web-research'
        self.config=self.folder/'settings.json'

    def settings(self):
        return json.loads(self.config.read_text(encoding='utf-8')) if self.config.exists() else {
            'enabled':False,'domains':DEFAULT_DOMAINS,'provider':'bing_public_rss','search_limit':10,'download_limit':10,
            'search_api_charge_cny':0,'note':'公开RSS搜索入口，无付费API；可用性以实际请求为准，不绕过挑战或登录'}

    def configure(self,data):
        if data.get('confirmed') is not True or type(data.get('enabled')) is not bool:raise ValueError('需要用户明确设置是否联网')
        domains=data.get('domains',self.settings()['domains'])
        if not isinstance(domains,list) or not 1<=len(domains)<=20:raise ValueError('允许1至20个来源域名')
        cleaned=[]
        for d in domains:
            if not isinstance(d,str) or not re.fullmatch(r'[a-z0-9]+(?:[.-][a-z0-9]+)+',d.lower()):raise ValueError('请填写域名，不含协议或路径')
            d=d.lower()
            if d in ('localhost','local','bing.com','com','org','net') or d.endswith(('.local','.localhost')):raise ValueError('来源域名过宽或不是原厂资料域名')
            try:ipaddress.ip_address(d)
            except ValueError:pass
            else:raise ValueError('不接受IP地址作为资料域名')
            cleaned.append(d)
        cfg=dict(self.settings(),enabled=data['enabled'],domains=sorted(set(cleaned)))
        atomic(self.config,cfg);return cfg

    def state_path(self,project_id):
        if str(UUID(project_id))!=project_id:raise ValueError('项目编号无效')
        return self.folder/(project_id+'.json')

    def state(self,project_id):
        path=self.state_path(project_id)
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'searches':{},'documents':{},'events':[]}

    def history(self,project_id):
        state=self.state(project_id)
        return {'searches':list(state['searches'].values()),'documents':list(state['documents'].values()),
                'events':state.get('events',[])[-20:],'parameters_verified':False}

    def retry_failed(self,project_id,confirmed):
        if confirmed is not True:raise ValueError('需要用户明确允许重新尝试失败的联网操作')
        with LOCK:
            state=self.state(project_id)
            # Do not reset consumed attempt quotas when the user permits a retry.
            state.setdefault('search_attempts',len(state['searches']))
            state.setdefault('download_attempts',len(state['documents']))
            removed=0
            for field in ('searches','documents'):
                for key in list(state[field]):
                    if state[field][key]['status'] in ('network_unavailable','no_matches','import_failed','pending','stale_source'):
                        del state[field][key];removed+=1
            state.setdefault('events',[]).append({'event':'user_allowed_retry_failed','count':removed,'time':datetime.now(timezone.utc).isoformat()})
            atomic(self.state_path(project_id),state)
            return {'retry_enabled_for':removed,'quotas_reset':False}

    def search(self,project_id,query):
        if not isinstance(query,str) or not 0<len(query.strip())<=200:raise ValueError('请用200字以内的型号与资料关键词，不提交完整项目描述或密钥')
        cfg=self.settings()
        if not cfg['enabled']:return {'status':'not_configured','matches':[],'reason':'自主联网尚未启用，可在资料面板开启或手动导入资料'}
        normalized=' '.join(query.split())
        key=hashlib.sha256(json.dumps([normalized.casefold(),cfg['domains']],sort_keys=True).encode()).hexdigest()
        with LOCK:
            state=self.state(project_id)
            if key in state['searches']:return dict(state['searches'][key],cached=True)
            if state.get('search_attempts',len(state['searches']))>=cfg['search_limit']:return {'status':'limit_reached','matches':[],'reason':'本项目联网检索次数已达上限，不重复尝试；请缩小缺口或提供原厂URL'}
            # Persist the attempt before network I/O; unknown interrupted work is not blindly replayed.
            result={'id':key,'query':normalized,'status':'pending','matches':[],'searched_at':datetime.now(timezone.utc).isoformat(),'parameters_verified':False}
            state['search_attempts']=state.get('search_attempts',len(state['searches']))+1
            state['searches'][key]=result;atomic(self.state_path(project_id),state)
            try:
                terms=normalized+' ('+' OR '.join('site:'+d for d in cfg['domains'])+')'
                page=fetch_public('https://www.bing.com/search?'+urlencode({'q':terms,'format':'rss'}),['bing.com'],1_000_000)
                if b'<!DOCTYPE' in page['raw'].upper() or b'<!ENTITY' in page['raw'].upper():raise ValueError('搜索返回非安全RSS，未绕过验证页')
                feed=ET.fromstring(page['raw'])
                if feed.tag.lower()!='rss':raise ValueError('搜索入口未返回RSS，不模拟搜索结果')
                matches=[];seen=set()
                for item in feed.findall('.//item'):
                    url=item.findtext('link','')
                    try:url=canonical(url)
                    except ValueError:continue
                    if not approved(url,cfg['domains']) or url in seen:continue
                    seen.add(url);matches.append({'title':item.findtext('title','')[:300],'url':url,'reviewed':False})
                    if len(matches)==3:break
                result.update(status='references_found' if matches else 'no_matches',matches=matches)
                if not matches:
                    # A search engine can return unrelated results. Known source
                    # URLs are an explicit fallback, not fabricated web hits.
                    anchors=re.findall(r'[A-Za-z][A-Za-z0-9-]*\d[A-Za-z0-9-]*',normalized)
                    catalog=json.loads(self.library.catalog.read_text(encoding='utf-8'))
                    seeds=[]
                    for doc in catalog['documents']:
                        text=(doc.get('title','')+' '+' '.join(doc.get('source_urls',[]))).casefold()
                        if not anchors or not any(a.casefold() in text for a in anchors):continue
                        for url in doc.get('source_urls',[]):
                            try:url=canonical(url)
                            except ValueError:continue
                            if approved(url,cfg['domains']) and url not in {s['url'] for s in seeds}:
                                seeds.append({'title':doc['title'],'url':url,'reviewed':False,'origin':'existing_catalog_source_url'})
                    if seeds:result.update(status='catalog_sources_available',matches=seeds[:3],reason='公开搜索未返回允许的原厂链接；改查本地目录已记录的真实原厂来源，不把这些当作新搜索命中')
            except (ValueError,OSError,ET.ParseError,http.client.HTTPException) as exc:
                result.update(status='network_unavailable',reason=str(exc)[:300])
            state['searches'][key]=result;atomic(self.state_path(project_id),state)
            return result

    def import_url(self,project_id,url):
        cfg=self.settings()
        if not cfg['enabled']:return {'status':'not_configured','reason':'自主联网尚未启用'}
        url=canonical(url)
        if not approved(url,cfg['domains']):raise ValueError('该来源不在用户允许的原厂域名列表中')
        with LOCK:
            state=self.state(project_id);key=hashlib.sha256(url.encode()).hexdigest()
            if key in state['documents']:
                previous=state['documents'][key]
                if previous['status']=='imported':
                    try:self.library.document(previous['document_id'])
                    except (ValueError,OSError):
                        previous=dict(previous,status='stale_source',reason='已导入资料或索引发生变化，不能复用旧成功结果；需核对后明确重试')
                        state['documents'][key]=previous;atomic(self.state_path(project_id),state)
                return dict(previous,cached=True)
            if state.get('download_attempts',len(state['documents']))>=cfg['download_limit']:return {'status':'limit_reached','reason':'本项目资料下载次数达到上限'}
            result={'url':url,'status':'pending','reviewed':False,'parameters_verified':False}
            state['download_attempts']=state.get('download_attempts',len(state['documents']))+1
            state['documents'][key]=result;atomic(self.state_path(project_id),state)
            try:
                response=fetch_public(url,cfg['domains']);doc=self.ingest(response,url)
                result.update(status='imported',document_id=doc['id'],source_url=doc['source_urls'][0],sha256=doc['sha256'],
                              title=doc['title'],pages=doc.get('pages'))
            except (ValueError,OSError,http.client.HTTPException,subprocess.SubprocessError) as exc:
                result.update(status='import_failed',reason=str(exc)[:300])
            state['documents'][key]=result;atomic(self.state_path(project_id),state)
            return result

    def ingest(self,response,requested_url):
        from .web_documents import extract
        raw=response['raw'];sha=hashlib.sha256(raw).hexdigest();identity='DOC-WEB-'+sha[:20]
        source=json.loads(self.library.catalog.read_text(encoding='utf-8'))
        existing=next((d for d in source['documents'] if d.get('sha256')==sha and d.get('retrieval_eligible')),None)
        if existing:
            self.library.document(existing['id']);return existing
        folder=self.root/'knowledge/official/online'/sha;folder.mkdir(parents=True,exist_ok=True)
        pdf=raw.startswith(b'%PDF-')
        if not pdf and response['mime'] not in ('text/html','application/xhtml+xml','text/plain'):raise ValueError('只接收原厂PDF、HTML或纯文本资料')
        original=folder/('original.pdf' if pdf else 'original.html' if response['mime']!='text/plain' else 'original.txt')
        original.write_bytes(raw)
        index=None;pages=None
        if pdf:
            # Separate process imposes a wall-time limit on PDF parsing.
            run=subprocess.run([sys.executable,'-m','embedded_agent.extract_online_pdf',str(original)],capture_output=True,timeout=25)
            if run.returncode!=0:raise ValueError('PDF正文提取失败或缺少提取器；保留原始文件，不标已入库')
            textfile=folder/'body.txt';index=folder/'pages.json'
            if not textfile.exists() or textfile.stat().st_size>16_000_000:raise ValueError('PDF文本超限')
            pages=len(json.loads(index.read_text(encoding='utf-8')));title=Path(urlsplit(response['url']).path).name
        else:
            content=raw.decode('utf-8',errors='replace')
            title,body=extract(content) if response['mime']!='text/plain' else (Path(urlsplit(response['url']).path).name,content)
            if len(body.strip())<100:raise ValueError('正文过少，未入库')
            textfile=folder/'body.txt';textfile.write_text(body,encoding='utf-8')
        relative=lambda p:p.relative_to(self.root).as_posix() if p else None
        doc={'id':identity,'title':title or identity,'category':'online_official_unreviewed','file':relative(original),
             'text':relative(textfile),'page_index':relative(index),'pages':pages,'sha256':sha,
             'source_urls':list(dict.fromkeys([response['url'],requested_url])),'retrieval_eligible':True,
             'reviewed':False,'parameters_verified':False,'downloaded_at':datetime.now(timezone.utc).isoformat()}
        old=self.library.catalog.read_bytes();source['documents'].append(doc)
        atomic(self.library.catalog,source)
        try:self.library.build()
        except Exception:
            restore=self.library.catalog.with_suffix('.rollback');restore.write_bytes(old);restore.replace(self.library.catalog)
            raise ValueError('新资料索引失败，目录已恢复；未宣称入库成功') from None
        return doc

    def research(self,project_id,query,missing_field=None):
        if missing_field is not None and (not isinstance(missing_field,str) or not 0<len(missing_field.strip())<=100):raise ValueError('缺失字段需为100字以内的具体说明')
        local=self.library.search(query,limit=3)
        if local and not missing_field:return {'matches':local,'status':'references_found','network_used':False,'parameters_verified':False}
        remote=self.search(project_id,query if not missing_field else (query+' '+missing_field)[:200])
        imports=[]
        for candidate in remote.get('matches',[])[:2]:imports.append(self.import_url(project_id,candidate['url']))
        matches=self.library.search(query,limit=3)
        return {'matches':matches,'status':'references_found' if matches else 'needs_external_evidence','requested_missing_field':missing_field,'field_verified':False,
                'network_used':not remote.get('cached',False) and remote.get('status') not in ('not_configured','limit_reached'),
                'online':remote,'imports':imports,'parameters_verified':False,
                'next_step':'Agent自行读取原文、调整检索词并核对型号/版本/工况；使用record_parameter自动核对参数，不让用户填写审核字段。仍无依据时保留缺口并继续独立任务，不重复同一检索或宣称通过。'}

    def autonomous_research(self,project_id,query,missing_field=None):
        """Bounded query refinement and original-page reading without user clicks."""
        variants=[query]
        if isinstance(query,str):
            translated=query
            for cn,en in {'定时器':'timer','通道':'channel','静态电流':'quiescent current','待机电流':'standby current','数据手册':'datasheet','参考手册':'reference manual','电压':'voltage','电流':'current'}.items():
                translated=translated.replace(cn,' '+en+' ')
            translated=' '.join(translated.split())[:200]
            if translated!=query:variants.append(translated)
            anchors=re.findall(r'[A-Za-z][A-Za-z0-9-]*\d[A-Za-z0-9-]*',query)
            if anchors:variants.append((max(anchors,key=len)+' '+(missing_field or 'datasheet reference manual'))[:200])
        attempts=[];pages=[];seen=set();last=None
        for variant in list(dict.fromkeys(variants))[:3]:
            last=self.research(project_id,variant,missing_field);attempts.append({'query':variant,'status':last['status'],'online_status':last.get('online',{}).get('status')})
            for match in last.get('matches',[])[:3]:
                key=(match['document_id'],match['page'])
                if key in seen:continue
                try:
                    page=self.library.page(*key);seen.add(key)
                    pages.append({**page,'text':page['text'][:16000],'text_truncated':len(page['text'])>16000})
                except (ValueError,OSError):continue
            # A concrete missing field requires the decider to inspect evidence;
            # success here only means sources have been read, never fact approval.
            if pages:break
            if last.get('online',{}).get('status') in ('not_configured','network_unavailable','limit_reached','pending'):break
        related=[]
        if missing_field:
            for page in pages:
                for url in page.get('related_pdf_urls',[]):
                    if any(term in url.lower() for term in ('datasheet','reference_manual','user_manual','application_note')) and url not in related:related.append(url)
            for url in related[:2]:
                try:
                    record=self.import_url(project_id,url)
                    if record['status']=='imported':
                        hits=self.library.search((query+' '+missing_field)[:300],limit=2,document_id=record['document_id'])
                        for hit in hits:
                            key=(hit['document_id'],hit['page'])
                            if key not in seen:
                                page=self.library.page(*key);seen.add(key);pages.append({**page,'text':page['text'][:16000],'text_truncated':len(page['text'])>16000})
                except (ValueError,OSError):continue
        return {**(last or {}),'attempts':attempts,'original_pages':pages[:5],
                'autonomous':True,'human_research_required':False,'parameters_verified':False,
                'next_step':'根据原文自行核对字段并调用record_parameter；证据不足时自主换取证方向或记录缺口、继续独立任务。不得要求用户搜索、下载或填写参数审核表。'}
