"""Submit an explicit analyst decision to the live controller; never invent a next step."""
import argparse
import json
from pathlib import Path
import urllib.request
from uuid import uuid4

def request(path,payload=None):
    req=urllib.request.Request('http://127.0.0.1:8765'+path,
        data=None if payload is None else json.dumps(payload,ensure_ascii=False).encode('utf-8'),
        headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=90) as response: return json.load(response)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-id'); parser.add_argument('--run-id')
    parser.add_argument('--action',required=True,choices=['design_plan','design_research','design_evaluate','design_recommend','search_documents','read_document_page','power_estimate'])
    parser.add_argument('--arguments',type=Path,required=True)
    parser.add_argument('--rationale',required=True); parser.add_argument('--expected',required=True)
    parser.add_argument('--source',default='Codex 外部分析者')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    run=request('/runs',{'project_id':args.project_id,'max_steps':30}) if not args.run_id else request('/runs/'+args.run_id)['run']
    context=request('/runs/'+run['id'])
    if context['run']['project_revision']!=context['project']['revision']:
        request('/runs/'+run['id']+'/refresh',{'revision':context['run']['revision']})
        context=request('/runs/'+run['id'])
    decision={'id':uuid4().hex,'project_revision':context['project']['revision'],'action':args.action,
        'arguments':json.loads(args.arguments.read_text(encoding='utf-8')),
        'rationale':args.rationale,'expected':args.expected,'source':args.source}
    request('/runs/'+run['id']+'/decisions',{'revision':context['run']['revision'],'decision':decision})
    result=request('/runs/'+run['id']+'/tick',{})
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'run_id':run['id'],'status':result['status'],'observation':result['observations'][-1]['status'],
                      'steps':result['steps']},ensure_ascii=False))
    if result['observations'][-1]['status']!='executed':
        raise RuntimeError('决策未执行，请检查已保存的拒绝或中断观察，勿盲目重试')

if __name__=='__main__': main()
