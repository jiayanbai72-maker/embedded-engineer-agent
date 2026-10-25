"""Model-authored draft deliverables, isolated from verified hardware artifacts."""
from copy import deepcopy
from pathlib import PurePosixPath
import hashlib
import json
from html import escape

STAGES = ('interfaces', 'circuit', 'firmware')

def save(previous, payload):
    stage = payload.get('stage')
    if stage not in STAGES: raise ValueError('stage需要interfaces、circuit或firmware')
    result = deepcopy(previous or {})
    index = STAGES.index(stage)
    if index and STAGES[index-1] not in result: raise ValueError('请先保存上一阶段的实际文件')
    files = payload.get('files')
    if not isinstance(files, dict) or not 1 <= len(files) <= 12: raise ValueError('需要1至12个实际文件')
    allowed = {'interfaces':('.md','.json'), 'circuit':('.svg','.json','.md'), 'firmware':('.c','.h','.md')}[stage]
    for name, body in files.items():
        if (not isinstance(name,str) or '/' in name or '\\' in name or ':' in name or
                PurePosixPath(name).name != name or not name.endswith(allowed)):
            raise ValueError('仅允许当前阶段的单层文件名')
        if not isinstance(body,str) or not body.strip() or len(body.encode())>70000: raise ValueError('文件内容为空或过大')
    for key in ('rationale','assumptions','open_items'):
        value=payload.get(key)
        if key=='rationale':
            if not isinstance(value,str) or not value.strip(): raise ValueError('需要简短设计依据')
        elif not isinstance(value,list) or not all(isinstance(x,str) and x.strip() for x in value): raise ValueError(key+'需要文本列表')
    if stage=='interfaces' and not any(n.endswith('.md') for n in files): raise ValueError('接口阶段需要Markdown接口/引脚表，未知项明确标TBD')
    if stage=='circuit':
        if 'connections.json' not in files: raise ValueError('电路阶段需要connections.json')
        net=json.loads(files['connections.json'])
        if not isinstance(net,dict) or not isinstance(net.get('connections'),list) or not 1 <= len(net['connections']) <= 80: raise ValueError('connections.json需要非空connections列表')
        lines=[]
        for i,c in enumerate(net['connections']):
            if not isinstance(c,dict) or not all(isinstance(c.get(k),str) and c[k].strip() for k in ('from','to','signal','status')): raise ValueError('每条连接需要from、to、signal、status文本')
            if c['status'] not in ('proposed','unverified'): raise ValueError('草案连接只能标proposed或unverified')
            y=70+i*80
            lines.append('<rect x="24" y="'+str(y)+'" width="380" height="44" fill="#eef5ff" stroke="#446"/><rect x="960" y="'+str(y)+'" width="400" height="44" fill="#eef5ff" stroke="#446"/><path d="M404 '+str(y+22)+' H960" stroke="#446" fill="none"/><text x="34" y="'+str(y+28)+'" font-size="14">'+escape(c['from'])+'</text><text x="970" y="'+str(y+28)+'" font-size="14">'+escape(c['to'])+'</text><text x="420" y="'+str(y+12)+'" font-size="13">'+escape(c['signal']+' / '+c['status'])+'</text>')
        # Deterministic, inert SVG connection draft from the submitted net list.
        # No untrusted SVG markup is admitted.
        files=deepcopy(files)
        for name in list(files):
            if name.endswith('.svg'): del files[name]
        files['connections.svg']='<svg xmlns="http://www.w3.org/2000/svg" width="1400" height="'+str(120+len(lines)*80)+'"><rect width="100%" height="100%" fill="white"/><text x="24" y="30" font-size="20">连接草案 · 非PCB生产图 · 电气与引脚待核实</text>'+''.join(lines)+'</svg>'
    if stage=='firmware' and not any(n.endswith('.c') for n in files): raise ValueError('固件阶段需要实际C源码')
    result[stage]={'files':deepcopy(files),'rationale':payload['rationale'],'assumptions':payload['assumptions'],
                   'open_items':payload['open_items'],'sha256':hashlib.sha256(json.dumps(files,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
                   'structural_check':'passed','firmware_build':'not_run','hardware':'not_run'}
    for later in STAGES[index+1:]: result.pop(later,None)
    result['next_stage']=STAGES[index+1] if index<2 else None
    result['scope']='unverified_engineering_draft'
    return result
