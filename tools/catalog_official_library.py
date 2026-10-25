"""Audit downloaded reference packs and publish a deduplicated discovery catalogue."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile
import collect_general_knowledge as g

ROOT=g.ROOT
LIB=ROOT/'knowledge/official'

def main():
    records=[]; failures=[]; manifests=[]
    for path in sorted(LIB.glob('*/manifest.json')):
        m=json.loads(path.read_text(encoding='utf-8')); manifests.append(path)
        for s in m['sources']:
            entry=dict(s,collection=path.parent.name)
            if s['status']=='downloaded': records.append(entry)
            else: failures.append(entry)
    # Expose a few explicitly selected documentation members; never extract paths wholesale.
    derived=[]
    for s in records:
        if not s['name'].startswith('ch32v003-') or not s['name'].endswith('.zip'): continue
        with ZipFile(ROOT/s['local_path']) as archive:
            selected=[n for n in archive.namelist() if n.endswith(('CH32V00x Evaluation Board Reference-EN.pdf','CH32V00xSCH.pdf','RISC-V QingKeV2 Microprocessor Debug Manual.pdf','WCH-LinkUserManual-EN.pdf'))]
            for member in selected:
                data=archive.read(member); name=Path(member).name
                path=LIB/'derived/WCH'/name; path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(data)
                entry={'name':name,'category':'mcu/WCH/archive-manuals','url':s['url']+'#archive-member='+member,
                    'local_path':path.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(data).hexdigest(),
                    'size_bytes':len(data),'status':'downloaded','reviewed':False,'derived_from':s['local_path'],
                    'archive_member':member,'parent_sha256':s['sha256'],'collection':'derived'}
                entry.update(g.extract(entry)); derived.append(entry)
    all_records=records+derived
    checks=[]; documents={}
    for s in all_records:
        path=ROOT/s['local_path']; problems=[]
        if not path.exists(): problems.append('missing_file')
        elif hashlib.sha256(path.read_bytes()).hexdigest()!=s['sha256']: problems.append('hash_mismatch')
        if s.get('extraction_status')=='failed': problems.append('text_extraction_failed')
        suffix=path.suffix.lower()
        if suffix=='.zip' and path.exists():
            try:
                with ZipFile(path) as archive:
                    bad=archive.testzip()
                    if bad: problems.append('zip_crc_failed:'+bad)
            except Exception as exc: problems.append('zip_invalid:'+str(exc)[:100])
        title=s.get('title') or s['name']
        text_path=s.get('text_path')
        if suffix in ('.txt','.md'): text_path=s['local_path']
        if suffix=='.html' and text_path:
            text=(ROOT/text_path).read_text(encoding='utf-8',errors='replace')
            if len(text.strip())<1000: problems.append('short_or_dynamic_html_not_offline_manual')
            if any(x in text[:2000].lower() for x in ('access denied','just a moment','verify you are human')):
                problems.append('possible_access_challenge')
            parser=g.base.Links()  # HTML title discovery uses source rather than generated filenames.
            import re
            match=re.search(r'<title[^>]*>(.*?)</title>',path.read_text(encoding='utf-8',errors='replace'),re.I|re.S)
            if match: title=re.sub(r'\s+',' ',match.group(1)).strip()
        if suffix=='.pdf' and not text_path: problems.append('pdf_not_indexed')
        checks.append({'file':s['local_path'],'issues':problems})
        key=s['sha256']
        if key in documents:
            documents[key]['alternate_files'].append(s['local_path'])
            documents[key]['source_urls'].append(s['url']); continue
        documents[key]={'id':'DOC-'+key[:16],'title':title,'category':s['category'],
            'file':s['local_path'],'alternate_files':[],'source_urls':[s['url']],
            'sha256':key,'bytes':s['size_bytes'],'text':text_path,'page_index':s.get('page_index'),
            'pages':s.get('pages'),'issues':problems,'reviewed':False,
            'retrieval_eligible':bool(text_path) and not problems,
            'scope':'reference_only_not_verified_selection_evidence',
            'derived_from':s.get('derived_from'),'archive_member':s.get('archive_member')}
    # A successful source in a later pack resolves earlier attempts to the same URL.
    successful_urls={s['url'] for s in records}
    unresolved={s['url']:s for s in failures if s['url'] not in successful_urls}
    summary={'generated_at_utc':datetime.now(timezone.utc).isoformat(),'downloaded_files':len(records),
       'unique_downloaded_sha256':len({s['sha256'] for s in records}), 'derived_documents':len(derived),
       'raw_mebibytes':round(sum(s['size_bytes'] for s in records)/1024**2,2),
       'pdf_files':sum(s['name'].lower().endswith('.pdf') for s in records),
       'pdfs_with_text':sum(s['name'].lower().endswith('.pdf') and bool(s.get('text_path')) for s in records),
       'retrieval_eligible_unique':sum(d['retrieval_eligible'] for d in documents.values()),
       'categories':len({s['category'] for s in records}),
       'hash_or_file_errors':sum(any(i in ('missing_file','hash_mismatch') for i in c['issues']) for c in checks),
       'unresolved_download_urls':len(unresolved),
       'note':'Eligibility checks file/text availability only. No parameter approval, automatic Agent integration, or complete-site mirroring.'}
    (LIB/'catalog.json').write_text(json.dumps({'schema_version':1,'summary':summary,'documents':list(documents.values())},ensure_ascii=False,indent=2),encoding='utf-8')
    (LIB/'audit.json').write_text(json.dumps({'summary':summary,'file_checks':checks,'unresolved_sources':list(unresolved.values())},ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# 通用嵌入式官方资料库','',
       f'已下载原始资源 **{summary["downloaded_files"]} 项**（按内容去重 {summary["unique_downloaded_sha256"]} 项），共 **{summary["raw_mebibytes"]} MiB**。',
       f'其中 PDF {summary["pdf_files"]} 份，成功提取文本 {summary["pdfs_with_text"]} 份；另从官方源码归档中单独提取手册 {len(derived)} 份。',
       '', '## 资料包','',
       '- [原项目候选器件与工具链](2026-10-15/收集结果.md)',
       '- [跨厂家器件、协议与工程软件](general-v1/收集结果.md)',
       '- [国产 MCU、GNSS、蜂窝、LoRa、以太网及显示存储](general-v1-extension/收集结果.md)',
       '- [重定向补充、乐鑫手册、CMSIS、Nordic、Arduino 与 Pico 示例](general-v1-supplement/收集结果.md)',
       '- [统一索引 catalog.json](catalog.json) / [质量与失败记录 audit.json](audit.json)',
       '', '## 按工程主题查找','',
       '| 主题 | 代表资料 |','|---|---|',
       '| 主控与架构 | STM32 F1/F4/G0/G4/L0/L4/U5/H7/WB/WL、ESP32 系列、RP2040/RP2350、NXP LPC55、GD32F30x、CH32、CMSIS、Nordic nrfx、Arduino AVR |',
       '| 传感器 | 温湿度、气压、CO₂、空气质量、颗粒物、光照、电流、霍尔、IMU、加速度、测距、电容与电感检测 |',
       '| 模拟与采集 | ADC、DAC、运放、称重采集、退耦与接地指南 |',
       '| 电源与电池 | LDO、降压、升压、升降压、充电、保护、电量计、负载开关、复位监控、USB PD |',
       '| 电机与执行 | 直流电机、步进、电磁阀、PWM 扩展、舵机、栅极驱动 |',
       '| 通信与接口 | Wi-Fi/BLE、蜂窝、GNSS、LoRa 驱动、以太网、RS485、RS232、CAN、电平转换、隔离 |',
       '| 应用协议 | I²C、MQTT、Modbus、CoAP、HTTP、TLS、JSON、CBOR |',
       '| 显示、音频与存储 | LED 驱动、LVGL、音频功放与编解码器、RTC、EEPROM、littlefs、摄像头驱动 |',
       '| 软件工程 | FreeRTOS、Zephyr、RT-Thread Nano、ESP-IDF、MicroPython、lwIP、coreMQTT、CMake、PlatformIO |',
       '| 测试与维护 | Unity、CMock、OpenOCD、MCUboot、OTA、编译器及链接器资料 |',
       '', '## 使用边界','',
       '原始资料的 reviewed=false 代表整篇文档没有被逐项审核。服务通过 tools/build_document_index.py 建立的离线索引提供检索；单项参数审核另存于 runtime/knowledge/parameters。源码 ZIP 未安装运行，子模块与构建依赖可能不齐。网页是单页快照；动态加载页面可能不含正文。PDF 文本不能替代原始图表。',
       '', '存在下载失败、解析失败或动态页面正文缺失的项目，已在 audit.json 标记；这些内容不会进入统一目录的可检索候选。历史包中的重复文件保留以便追溯，统一索引按 SHA-256 合并。',
       '', '## 仍需扩展','',
       'AT32/HC32/MM32 等国产 MCU、更多显示控制器与摄像头、电池和电源模块完整参考设计、USB/BLE/CAN 等协议的完整授权规范、EMC/ESD 与可靠性验证资料仍未形成完整覆盖。采购报价与硬件实测需另外收集。',
       '', '资料覆盖按项目需要持续扩充，不声称本地已覆盖所有芯片或全部官方文档。']
    (LIB/'README.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False),flush=True)

if __name__=='__main__': main()
