"""Collect bounded public official sources. Download only; never execute or install attachments."""
import concurrent.futures
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import re
import subprocess
import urllib.parse
import urllib.request
from zipfile import ZipFile, is_zipfile

ROOT = Path(__file__).absolute().parents[1]
OUT = ROOT / 'knowledge' / 'official' / '2026-10-15'
MAX_BYTES = 160 * 1024 * 1024
HEADERS = {'User-Agent': 'EmbeddedEngineerKnowledgeCollector/0.1', 'Accept': '*/*'}
SEEDS = [
 ('voice/SU21T', 'https://docs.aimachip.com/zh-cn/latest/file/offlineVoice/SU21T.html'),
 ('voice/SU03T-reference', 'https://docs.aimachip.com/zh-cn/latest/file/offlineVoice/SU03T.html'),
 ('voice/hummingbird-L', 'https://docs.aimachip.com/zh-cn/latest/file/chip/L.html'),
 ('mcu/STM32L031K6', 'https://www.st.com/en/microcontrollers-microprocessors/stm32l031k6.html'),
 ('boards/NUCLEO-L031K6-reference', 'https://www.st.com/en/evaluation-tools/nucleo-l031k6.html'),
 ('actuators/SG90-original-reference', 'https://towerpro.com.tw/product/sg90-7/'),
 ('toolchains/armcc', 'https://www.keil.com/support/man/docs/armcc/'),
 ('toolchains/armlink', 'https://www.keil.com/support/man/docs/armlink/default.htm'),
 ('toolchains/fromelf', 'https://www.keil.com/support/man/docs/armutil/default.htm'),
]


def allowed(url):
    parsed = urllib.parse.urlsplit(url)
    host = (parsed.hostname or '').lower()
    return parsed.scheme == 'https' and any(host == d or host.endswith('.'+d) for d in
        ('aimachip.com', 'st.com', 'st.com.cn', 'towerpro.com.tw', 'keil.com', 'arm.com', 'github.com', 'githubusercontent.com', 'codeload.github.com'))


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed(newurl):
            raise ValueError('redirect outside official allowlist')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url):
    url = urllib.parse.quote(url, safe=':/?=&%+@,;')
    if not allowed(url):
        raise ValueError('source outside allowlist')
    with urllib.request.build_opener(SafeRedirect()).open(urllib.request.Request(url, headers=HEADERS), timeout=45) as response:
        if int(response.headers.get('Content-Length', '0')) > MAX_BYTES:
            raise ValueError('resource exceeds 160MiB limit')
        data = response.read(MAX_BYTES+1)
        if len(data) > MAX_BYTES:
            raise ValueError('resource exceeds 160MiB limit')
        return data, response.geturl(), response.headers.get('Content-Type', '')


class Links(HTMLParser):
    def __init__(self):
        super().__init__(); self.links=[]; self.images=[]
    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if tag == 'a' and attrs.get('href'): self.links.append(attrs['href'])
        if tag == 'img' and attrs.get('src'): self.images.append(attrs['src'])


def task(category, url, name=None, source_page=None, note=None):
    name = name or urllib.parse.unquote(urllib.parse.urlsplit(url).path.rsplit('/',1)[-1]) or 'index.html'
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name)[:140]
    return {'category':category,'url':url,'name':name,'source_page':source_page,'note':note}


def save(item):
    result=dict(item, status='failed', reviewed=False)
    try:
        data, final, content_type=fetch(item['url'])
        suffix=Path(item['name']).suffix.lower()
        if suffix == '.pdf' and not data.lstrip().startswith(b'%PDF'):
            raise ValueError('expected PDF but received another format')
        if suffix == '.zip' and not is_zipfile(io.BytesIO(data)):
            raise ValueError('expected ZIP but received another format')
        path=OUT/item['category']/item['name']
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(data)
        result.update(status='downloaded',final_url=final,content_type=content_type,
                      local_path=path.relative_to(ROOT).as_posix(),sha256=hashlib.sha256(data).hexdigest(),size_bytes=len(data))
        if suffix == '.zip':
            with ZipFile(io.BytesIO(data)) as archive:
                result['archive_entries']=len(archive.infolist())
                index=path.with_suffix('.contents.txt')
                index.write_text('\n'.join(x.filename for x in archive.infolist()),encoding='utf-8')
                result['archive_index']=index.relative_to(ROOT).as_posix()
        if suffix == '.pdf':
            converter=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler/Library/bin/pdftotext.exe'
            if converter.is_file():
                text_path=path.with_suffix('.txt')
                run=subprocess.run([str(converter),'-layout','-enc','UTF-8',str(path),str(text_path)],capture_output=True,timeout=60)
                if run.returncode == 0 and text_path.is_file():
                    extracted=text_path.read_text(encoding='utf-8')
                    result['text_path']=text_path.relative_to(ROOT).as_posix()
                    result['text_characters']=len(extracted)
                    result['pages']=len(extracted.split('\f'))-1
                    result['extraction_status']='text_available' if extracted.strip() else 'needs_ocr'
                else: result['extraction_status']='failed'
            else: result['extraction_status']='converter_unavailable'
        print(json.dumps({'status':result['status'],'file':item['name'],'bytes':len(data)},ensure_ascii=False),flush=True)
    except Exception as exc:
        result['error']=str(exc)[:300]
        print(json.dumps({'status':'failed','file':item['name'],'error':result['error']},ensure_ascii=False),flush=True)
    return result


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    manifest={'collected_at_utc':datetime.now(timezone.utc).isoformat(),'scope':'official-source collection, not verified component parameters',
              'sources':[],'discovery_errors':[],'repository_pins':[]}
    downloads=[]
    for category,url in SEEDS:
        entry=save(task(category,url,'source-page.html',note='Reference board / alternative modules do not imply final selection.'))
        manifest['sources'].append(entry)
        if entry['status']!='downloaded': continue
        parser=Links(); parser.feed((ROOT/entry['local_path']).read_text(encoding='utf-8',errors='replace'))
        candidates=[]
        for href in parser.links:
            target=urllib.parse.urljoin(url,href).split('#')[0]
            path=urllib.parse.urlsplit(target).path.lower()
            if not allowed(target) or not path.endswith(('.pdf','.zip','.chm')): continue
            if category.startswith('mcu/') and not any(x in path for x in ('stm32l0','rm0377','es0322','an2606','an4445','an4467','an4776')): continue
            if category.startswith('boards/') and not any(x in path for x in ('nucleo','mb1180','um1956','l031')): continue
            candidates.append(target)
        for target in sorted(set(candidates))[:30]: downloads.append(task(category,target,source_page=url))
        if category.startswith(('voice/','actuators/')):
            images=[urllib.parse.urljoin(url,x) for x in parser.images if '_images/' in x]
            for target in images[:10]:
                if allowed(target): downloads.append(task(category+'/images',target,source_page=url,note='Pinout/parameter diagrams require visual review.'))
    fixed=[
      ('mcu/STM32L031K6','https://www.st.com/resource/en/datasheet/stm32l031k6.pdf'),
      ('mcu/STM32L031K6','https://www.st.com/resource/en/reference_manual/dm00108282.pdf'),
      ('mcu/STM32L031K6','https://www.st.com/resource/en/errata_sheet/es0322-stm32l031xxl041xx-device-errata-stmicroelectronics.pdf'),
      ('mcu/STM32L031K6','https://www.st.com/resource/en/application_note/an4445-stm32l0xx-ultralow-power-features-overview-stmicroelectronics.pdf')]
    downloads.extend(task(c,u) for c,u in fixed)
    # Pin each dependency to the commit referenced by the parent, not unrelated latest driver versions.
    try:
        repo='STMicroelectronics/STM32CubeL0'
        tags=json.loads(fetch('https://api.github.com/repos/'+repo+'/tags?per_page=1')[0])
        sha=tags[0]['commit']['sha']; tag=tags[0]['name']
        tree=json.loads(fetch('https://api.github.com/repos/'+repo+'/git/trees/'+sha+'?recursive=1')[0])
        gitmodules=fetch('https://raw.githubusercontent.com/'+repo+'/'+sha+'/.gitmodules')[0].decode()
        paths={}
        for block in gitmodules.split('[submodule ')[1:]:
            p=re.search(r'path\s*=\s*(.+)',block); u=re.search(r'url\s*=\s*(.+)',block)
            if p and u: paths[p.group(1).strip()]=u.group(1).strip()
        dependencies=[]
        for entry in tree['tree']:
            if entry['type']=='commit' and any(x in entry['path'] for x in ('CMSIS/Device/ST/STM32L0xx','STM32L0xx_HAL_Driver')):
                dependency=paths.get(entry['path'],'').removesuffix('.git')
                if dependency.startswith('https://github.com/STMicroelectronics/'):
                    dep_repo=dependency.split('github.com/',1)[1]
                    dependencies.append({'repository':dep_repo,'commit':entry['sha'],'parent_path':entry['path']})
                    downloads.append(task('sdk',f'https://codeload.github.com/{dep_repo}/zip/{entry["sha"]}',dep_repo.split('/')[-1]+'-'+entry['sha'][:12]+'.zip',note='Pinned submodule; retain upstream license.'))
        manifest['repository_pins'].append({'repository':repo,'tag':tag,'commit':sha,'dependencies':dependencies,
                                            'uncollected_submodules':[e['path'] for e in tree['tree'] if e['type']=='commit' and not any(d['parent_path']==e['path'] for d in dependencies)]})
        downloads.append(task('sdk',f'https://codeload.github.com/{repo}/zip/{sha}','STM32CubeL0-'+tag+'-'+sha[:12]+'.zip',note='Main archive excludes submodule content; pinned HAL/device archives collected separately.'))
        for name in ('README.md','.gitmodules','Release_Notes.html','LICENSE.md'):
            downloads.append(task('sdk/metadata','https://raw.githubusercontent.com/'+repo+'/'+sha+'/'+name,name))
    except Exception as exc:
        manifest['discovery_errors'].append({'source':'STM32CubeL0','error':str(exc)[:300]})
    unique={}
    for item in downloads: unique.setdefault(item['url'],item)
    (OUT/'discovered-downloads.json').write_text(json.dumps(list(unique.values()),ensure_ascii=False,indent=2),encoding='utf-8')
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for entry in pool.map(save,unique.values()):
            manifest['sources'].append(entry)
            (OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    ok=[x for x in manifest['sources'] if x['status']=='downloaded']
    failed=[x for x in manifest['sources'] if x['status']!='downloaded']
    summary=['# 官方资料收集结果','',f'成功 {len(ok)} 项，失败 {len(failed)} 项，原文件合计 {sum(x["size_bytes"] for x in ok)/1024/1024:.2f} MiB。',
             '','原始资料已保存；参数尚未逐项审核。ZIP只检查目录，不运行或安装其中程序。',
             '','NUCLEO板卡、SU-03T为参考/备选，不能代替最终购买板卡或模块资料。',
             '','## 已下载','']
    summary.extend(f'- [{x["category"]}/{x["name"]}]({Path(x["local_path"]).relative_to(OUT.relative_to(ROOT)).as_posix()})' for x in ok)
    summary.extend(['','## 需要补充或重试',''])
    summary.extend(f'- {x["name"]}：{x.get("error", "failed")}；来源 {x["url"]}' for x in failed)
    summary.extend(f'- {x["source"]}：{x["error"]}' for x in manifest['discovery_errors'])
    summary.extend(['','## 尚需真实选型或测量','', '实际购买板卡、最终电池/电源、当前报价和整机电流测量尚不具备，不能凭收集资料自动判定100元与48小时达标。'])
    (OUT/'收集结果.md').write_text('\n'.join(summary),encoding='utf-8')
    print(json.dumps({'downloaded':len(ok),'failed':len(failed),'directory':str(OUT),'discovery_errors':manifest['discovery_errors']},ensure_ascii=False),flush=True)


if __name__=='__main__': main()
