"""Supplement useful official manuals and create page-addressable local text indexes."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import re
from pypdf import PdfReader
from collect_official_knowledge import ROOT, OUT, task, save, fetch

EXTRA = [
 ('boards/NUCLEO-L031K6-reference','https://www.st.com/resource/en/user_manual/dm00231744.pdf','UM1956-Nucleo32-MB1180.pdf'),
 ('mcu/STM32L031K6','https://www.st.com/resource/en/user_manual/um1749-description-of-stm32l0-hal-and-low-layer-drivers-stmicroelectronics.pdf','UM1749-STM32L0-HAL-LL.pdf'),
 ('mcu/STM32L031K6','https://www.st.com/resource/en/application_note/an4467-getting-started-with-stm32l0xx-hardware-development-stmicroelectronics.pdf','AN4467-STM32L0-hardware.pdf'),
 ('mcu/STM32L031K6','https://www.st.com/resource/en/application_note/an4776-generalpurpose-timer-cookbook-for-stm32-microcontrollers-stmicroelectronics.pdf','AN4776-timer-cookbook.pdf'),
 ('mcu/STM32L031K6','https://www.st.com/resource/en/application_note/an2606-stm32-microcontroller-system-memory-boot-mode-stmicroelectronics.pdf','AN2606-system-boot-mode.pdf'),
 ('mcu/STM32L031K6','https://www.st.com/resource/en/application_note/an3155-usart-protocol-used-in-the-stm32-bootloader-stmicroelectronics.pdf','AN3155-USART-bootloader.pdf'),
 ('toolchains/armcc','https://documentation-service.arm.com/static/5f721c6c1b758617cd950f6f','ARMCC-v5.06-user-guide.pdf'),
 ('toolchains/armlink','https://documentation-service.arm.com/static/5f72de911b758617cd9536a6','ARMLINK-v5.06-user-guide.pdf'),
]


def extract(entry):
    entry=dict(entry)
    path=ROOT/entry['local_path']
    try:
        reader=PdfReader(path)
        text_path=path.with_suffix('.txt')
        pages=[]; offset=0
        with text_path.open('w',encoding='utf-8') as output:
            for number,page in enumerate(reader.pages,1):
                text=page.extract_text() or ''
                pages.append({'page':number,'offset':offset,'length':len(text)})
                output.write(text+'\f')
                offset+=len(text)+1
        index=text_path.with_suffix('.pages.json')
        index.write_text(json.dumps(pages,ensure_ascii=False),encoding='utf-8')
        entry.update(text_path=text_path.relative_to(ROOT).as_posix(),page_index=index.relative_to(ROOT).as_posix(),
                     pages=len(pages),text_characters=offset,extraction_status='text_available' if offset>len(pages) else 'needs_ocr')
        print(json.dumps({'extracted':entry['name'],'pages':len(pages),'characters':offset},ensure_ascii=False),flush=True)
    except Exception as exc:
        entry['extraction_status']='failed';entry['extraction_error']=str(exc)[:250]
    return entry


def main():
    manifest=json.loads((OUT/'manifest.json').read_text(encoding='utf-8'))
    known={e['url'] for e in manifest['sources'] if e['status']=='downloaded'}
    extra=[task(c,u,n,note='Supplemental official manual; applicability must be checked before implementation.') for c,u,n in EXTRA if u not in known]
    try:
        pin=manifest['repository_pins'][0]
        repo=pin['repository']; sha=pin['commit']
        tree=json.loads(fetch('https://api.github.com/repos/'+repo+'/git/trees/'+sha+'?recursive=1')[0])
        modules=fetch('https://raw.githubusercontent.com/'+repo+'/'+sha+'/.gitmodules')[0].decode()
        for path in ('Drivers/BSP/STM32L0xx_Nucleo_32','Drivers/BSP/Components/Common'):
            entry=next(e for e in tree['tree'] if e['path']==path and e['type']=='commit')
            block=next(b for b in modules.split('[submodule ')[1:] if re.search(r'path\s*=\s*'+re.escape(path)+r'\s*\n',b))
            url=re.search(r'url\s*=\s*(.+)',block).group(1).strip().removesuffix('.git')
            if not url.startswith('https://github.com/STMicroelectronics/'):
                raise ValueError('non-official SDK dependency')
            dep_repo=url.split('github.com/',1)[1]
            archive='https://codeload.github.com/'+dep_repo+'/zip/'+entry['sha']
            if archive not in known:
                extra.append(task('sdk',archive,dep_repo.split('/')[-1]+'-'+entry['sha'][:12]+'.zip',note='Pinned reference-board BSP dependency.'))
                pin['dependencies'].append({'repository':dep_repo,'commit':entry['sha'],'parent_path':path})
                pin['uncollected_submodules']=[p for p in pin['uncollected_submodules'] if p!=path]
    except Exception as exc:
        manifest['discovery_errors'].append({'source':'additional SDK BSP','error':str(exc)[:250]})
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for entry in pool.map(save,extra):
            manifest['sources'].append(entry)
            (OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    indices=[i for i,e in enumerate(manifest['sources']) if e['status']=='downloaded' and e['name'].lower().endswith('.pdf')]
    with concurrent.futures.ProcessPoolExecutor(max_workers=3) as pool:
        for i,result in zip(indices,pool.map(extract,[manifest['sources'][i] for i in indices])):
            manifest['sources'][i]=result
            (OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    documents=[]
    for entry in manifest['sources']:
        if entry.get('text_path'):
            documents.append({'id':'DOC-'+entry['sha256'][:16],'scope':'device_reference','category':entry['category'],
                              'title':entry['name'],'source_url':entry['url'],'sha256':entry['sha256'],
                              'file':entry['local_path'],'text':entry['text_path'],'page_index':entry.get('page_index'),
                              'reviewed':False,'note':'Extracted text is searchable; tables, diagrams and conditions still require review.'})
    (OUT/'document-index.json').write_text(json.dumps({'schema_version':1,'documents':documents},ensure_ascii=False,indent=2),encoding='utf-8')
    good=[e for e in manifest['sources'] if e['status']=='downloaded']; bad=[e for e in manifest['sources'] if e['status']!='downloaded']
    lines=['# 官方资料下载与索引结果','',f'原始资源成功 {len(good)} 项，失败链接 {len(bad)} 项，PDF文本索引 {len(documents)} 份。',
           f'原文件总计 {sum(e["size_bytes"] for e in good)/1024/1024:.2f} MiB。','',
           'manifest.json保留来源、哈希、体积、页数、SDK版本与失败原因；document-index.json保留可检索文档索引。',
           'reviewed=false：下载和提取不等于参数审核。没有执行归档内程序。','',
           '## 下载内容','']
    for e in good:
        relative=Path(e['local_path']).relative_to(OUT.relative_to(ROOT)).as_posix()
        lines.append(f'- [{e["category"]}/{e["name"]}]({relative})')
    lines+=['','## 失效链接与替代','']
    for e in bad:
        lines.append(f'- {e["name"]}：{e.get("error")}; 来源 {e["url"]}')
    lines+=['','旧Keil PDF链接可能失效；已另外收集可访问的官方ARM编译/链接PDF及文档页，不将404当下载成功。',
            '','## 仍未具备','',
            '实际购买板卡、电池、电源模块尚未选定；参考NUCLEO和备选SU-03T不能替代最终器件。',
            'SG90网页资料不等于实际购买舵机的堵转电流测试。价格、运费和整机监听/动作功耗仍需报价与测量。',
            'STM32CubeL0主包与相关HAL/CMSIS/BSP按父仓库引用提交保存为独立归档；未下载的无关子模块列在manifest，不声称全依赖安装完成。']
    (OUT/'收集结果.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps({'downloaded':len(good),'failed_links':len(bad),'indexed_pdfs':len(documents),'megabytes':round(sum(e['size_bytes'] for e in good)/1024/1024,2)},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
