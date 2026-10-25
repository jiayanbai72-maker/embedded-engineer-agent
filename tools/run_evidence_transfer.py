"""Opt-in live transfer test on synthetic, non-component-specific evidence only."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
from test_architecture import ArchitectureTests
from embedded_agent.local_model import LocalSettings
from embedded_agent.service import EngineeringService
from embedded_agent.control import DecisionController
from embedded_agent.autonomy import AutonomousRunner,ModelDecider


def case(model,kind):
    fixture=ArchitectureTests();fixture.setUp()
    try:
        folder=fixture.root/'knowledge/official';folder.mkdir()
        chip='QZ241' if kind=='relation' else 'MV672'
        content=('Synthetic test only. QZ241 signal mapping table.\nPin | Bank | Signal\nQ7 | MX3 | EVT8_IN\nNo real hardware specifications.\n' if kind=='relation' else 'Synthetic test only. MV672 recommended supply voltage minimum is 1.8 V under synthetic fixture conditions.\nNo real hardware specifications.\n')
        raw=folder/'synthetic.txt';raw.write_text(content,encoding='utf-8')
        doc={'id':'DOC-'+chip,'title':chip+' synthetic test evidence','category':'synthetic','file':'knowledge/official/synthetic.txt','text':'knowledge/official/synthetic.txt','sha256':hashlib.sha256(raw.read_bytes()).hexdigest(),'source_urls':['https://example.invalid/synthetic-only'],'retrieval_eligible':True}
        (folder/'catalog.json').write_text(json.dumps({'documents':[doc]}),encoding='utf-8')
        service=EngineeringService(fixture.root);service.app.documents.build()
        service.web.configure({'enabled':False,'domains':['example.invalid'],'confirmed':True})
        target=('登记QZ241中Q7在MX3对应EVT8_IN的原文关系' if kind=='relation' else '登记MV672的recommended_supply_min_v=1.8 V，工况为synthetic fixture conditions')
        project=service.app.store.create('仅为合成资料迁移测试：'+target+'。引用错误后自行读取同一原文修正；必须成功登记后结束，不运行硬件。')
        project.status='documents_delivered';service.app.store.save(project)
        control=DecisionController(service);run=control.create(project.id,max_steps=7,max_repairs=0,scope='research_only')
        args=dict(document_id=doc['id'],page=None,model=chip,conditions='synthetic fixture conditions',rationale='Injected stale reference to test autonomous recovery',quote_id='expired-reference')
        if kind=='relation':args.update(subject='Q7',predicate='MX3',object='EVT8_IN');action='record_fact'
        else:args.update(parameter='recommended_supply_min_v',value=1.8,unit='V');action='record_parameter'
        run['evidence_goal']={k:args[k] for k in ('model','subject','predicate','object','parameter','value','unit') if k in args};control.save(run)
        control.submit(run['id'],run['revision'],dict(id='injected-reference-failure',project_revision=project.revision,action=action,arguments=args,rationale='Frozen fault injection; not a model answer',expected='Reject stale source reference',source='synthetic_fault_injection'))
        with patch('embedded_agent.local_model.LocalSettings.model',return_value=model):
            run=control.advance(run['id']);run['auto_feedback']=run['observations'][-1]['tool_result'];run['auto_errors']=1;control.save(run)
            runner=AutonomousRunner(control,ModelDecider(model));trace=[]
            for _ in range(10):
                result=runner.step(run['id']);trace.append({'status':result['status'],'message':result['message']})
                if result['status']!='continue':break
        run=control.load(run['id'])
        registered=service.app.parameters.facts() if kind=='relation' else service.app.parameters.list()
        passed=any(p.get('valid') and p.get('model')==chip and ((p.get('subject')=='Q7' and p.get('predicate')=='MX3' and p.get('object')=='EVT8_IN') if kind=='relation' else (p.get('parameter')=='recommended_supply_min_v' and p.get('value')==1.8 and p.get('unit')=='V')) for p in registered)
        return {'case':kind,'synthetic':True,'passed':passed,'completed':run['status']=='complete','automatic_source_reads':len(run.get('source_recovery_attempts',{})),'steps':run['steps'],'trace':trace,'observations':run['observations']}
    finally:fixture.tearDown()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true');args=parser.parse_args()
    if not args.live:raise SystemExit('Use --live explicitly; tests consume the existing daily model budget.')
    model=LocalSettings(ROOT).model()
    if model is None:raise SystemExit('Configured model unavailable')
    before=model.budget.status()['accounted_cny'];results=[]
    for kind in ('relation','numeric'):
        result=case(model,kind);results.append(result)
        print(json.dumps({k:result[k] for k in ('case','passed','completed','automatic_source_reads','steps')},ensure_ascii=False),flush=True)
        if not result['passed']:break
    report={'cases':results,'all_passed':len(results)==2 and all(r['passed'] and r['completed'] for r in results),'accounted_cost_cny':model.budget.status()['accounted_cny']-before,'limitation':'Two synthetic source-reference recovery cases, not proof of general autonomous engineering capability.'}
    folder=ROOT/'runtime/orchestration';folder.mkdir(parents=True,exist_ok=True)
    (folder/'transfer-live.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='cases'},ensure_ascii=False),flush=True)
