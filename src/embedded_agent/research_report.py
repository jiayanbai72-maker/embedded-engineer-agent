"""Deterministic evidence binding for a bounded PWM assignment review."""
import re


def evaluate(data,facts):
    valid={f['id']:f for f in facts if f.get('valid')}
    gaps=[];pins=[];signals=[]
    mappings=data['mappings'];voice=data['voice_pins'];model=data['model'];package=data['package']
    if len(mappings)!=3:gaps.append('尚未提供三路PWM映射')
    for m in mappings:
        pins.append(m['pin']);signals.append(m['signal'])
        fact=valid.get(m['fact_id'],{})
        if not (fact.get('model')==model and fact.get('subject')==m['pin'] and fact.get('predicate')==m['af'] and fact.get('object')==m['signal']):
            gaps.append(m['pin']+'：缺少有效引脚复用关系证据')
        if not re.fullmatch(r'TIM\d+_CH[1-9]\d*',m['signal']):gaps.append(m['pin']+'：信号不是独立定时器通道')
        package_fact=valid.get(m.get('package_fact_id'),{})
        if not (package_fact.get('model')==model and package_fact.get('subject')==m['pin'] and package_fact.get('predicate')=='package' and package_fact.get('object')==package):
            gaps.append(m['pin']+'：缺少指定封装引出证据')
        m['physical_pin']=package_fact.get('pin_number')
    if len(set(pins))!=len(pins):gaps.append('PWM引脚重复')
    if len(set(signals))!=len(signals):gaps.append('PWM通道重复')
    if not voice:gaps.append('语音接口引脚尚未明确，不能判断冲突')
    for pin in voice:
        fact=valid.get(pin['fact_id'],{})
        if not (fact.get('model')==model and fact.get('subject')==pin['pin'] and fact.get('predicate')==pin['af'] and fact.get('object')==pin['signal']):gaps.append(pin['pin']+'：语音接口缺少复用证据')
        if pin['pin'] in pins:gaps.append(pin['pin']+'：PWM与语音接口引脚冲突')
        package_fact=valid.get(pin.get('package_fact_id'),{})
        if not (package_fact.get('model')==model and package_fact.get('subject')==pin['pin'] and package_fact.get('predicate')=='package' and package_fact.get('object')==package):gaps.append(pin['pin']+'：语音引脚缺少指定封装引出证据')
        pin['physical_pin']=package_fact.get('pin_number')
    if len({p['pin'] for p in voice})!=len(voice):gaps.append('语音接口引脚重复')
    uart=[re.fullmatch(r'((?:USART|UART|LPUART)\d+)_(TX|RX)',p['signal']) for p in voice]
    if len(uart)!=2 or not all(uart) or {m.group(2) for m in uart if m}!={'TX','RX'} or len({m.group(1) for m in uart if m})!=1:
        gaps.append('语音UART尚未形成同一外设的TX/RX配对')
    # The verdict covers only the explicit, source-bound wiring checks above.
    # Free-text model concerns remain visible but cannot redefine this scope.
    gaps=list(dict.fromkeys(gaps))
    used={m.get(key) for m in mappings+voice for key in ('fact_id','package_fact_id')}
    sources=[{k:f.get(k) for k in ('id','document_id','page','source_url','source_view')} for identity,f in valid.items() if identity in used]
    return {'status':'needs_evidence' if gaps else 'passed','summary':'已按来源编号检查候选接线；'+('仍有证据缺口，见下列项目。' if gaps else '所提交三路PWM与语音UART的映射、封装引出及引脚冲突检查通过，未做实机验证。'),'model_note':data['summary'],'model':model,'package':package,
            'mappings':mappings,'voice_pins':voice,'gaps':gaps,'sources':sources,'model_concerns':data.get('unresolved',[]),'deferred':data.get('deferred',[]),'hardware_verified':False,
            'scope':'仅为候选引脚复用、封装引出和语音占用的证据检查；不代表完整电气审查、固件或实机验证。'}


def export(root,run_id,report):
    from pathlib import Path
    import csv
    folder=Path(root)/'runtime/research-reports'/run_id;folder.mkdir(parents=True,exist_ok=True)
    lines=['# 候选接线表与证据检查','', '状态：'+report['status'],'',report['scope'],'',
           '器件系列：'+report['model']+'；候选封装：'+report['package'],'',
           '| 用途 | 引脚 | 物理脚号 | 复用 | 外设信号 | 关系证据 | 封装证据 |','|---|---|---|---|---|---|---|']
    rows=[]
    for purpose,items in (('PWM',report['mappings']),('语音UART',report['voice_pins'])):
        for m in items:
            row=[purpose,m['pin'],m.get('physical_pin') or '待核对',m['af'],m['signal'],m.get('fact_id',''),m.get('package_fact_id') or '待核对'];rows.append(row)
            lines.append('| '+' | '.join(str(v).replace('|','\\|').replace('\n',' ') for v in row)+' |')
    lines+=['','## 待核对项','']+['- '+gap for gap in report['gaps']]
    if not report['gaps']:lines.append('本轮提交的接线证据无未通过项。')
    lines+=['','## 后续验证（不属于本轮通过范围）','']+['- '+item for item in report.get('deferred',[])]
    if report.get('model_concerns'):lines+=['','## Agent补充说明（不扩大本轮通过范围）','']+['- '+item for item in report['model_concerns']]
    lines+=['','## 原厂证据来源','']
    for source in report.get('sources',[]):
        lines.append('- '+source['id']+'：'+str(source.get('document_id'))+'，PDF物理页 '+str(source.get('page'))+'，'+str(source.get('source_url'))+('#page='+str(source['page']) if source.get('page') else ''))
    lines+=['','本表由Agent提交的专项报告导出；不包含供电、舵机负载接线或实物通电授权。100元预算及48小时续航目标仍待验证。']
    (folder/'候选接线表.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    with (folder/'候选接线表.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.writer(stream);writer.writerow(['用途','引脚','物理脚号','复用','外设信号','关系证据','封装证据']);writer.writerows(rows)
    return {name:str(folder/name) for name in ('候选接线表.md','候选接线表.csv')}
