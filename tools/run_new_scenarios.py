"""Opt-in live tests of new product analysis, with isolated persistent evidence."""
import argparse
import json
from pathlib import Path
import random
import sys
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
from test_architecture import ArchitectureTests
from embedded_agent.service import EngineeringService
from embedded_agent.control import DecisionController
from embedded_agent.autonomy import AutonomousRunner,ModelDecider
from embedded_agent.local_model import LocalSettings,BudgetPaused

POOL=[
 ('leak','电池供电的漏水报警器，放在洗衣机旁，探测积水后本地蜂鸣并亮灯，不联网。目标连续待机30天，材料预算80元。只做需求分析和至少两种候选方案，不采购、不接电、不运行硬件。'),
 ('light','床头感应小夜灯，USB 5V供电，环境暗且有人经过时亮30秒，可按键常亮；不联网。材料预算60元。只做需求分析和至少两种候选方案，不采购、不接电、不运行硬件。'),
 ('timer','离线学习计时器，两个按键，25分钟专注和5分钟休息，蜂鸣提示，可暂停继续，USB供电，无屏幕也可用LED显示状态，预算50元。只做需求分析和至少两种候选方案，不采购、不接电、不运行硬件。'),
 ('door','仓库门长时间未关报警器，门打开超过60秒蜂鸣，关门停止；可按键临时静音5分钟，USB供电，不联网，预算70元。只做需求分析和至少两种候选方案，不采购、不接电、不运行硬件。'),
 ('plant','室内盆栽缺水提醒器，每小时测一次土壤湿度，只用LED提醒，不控制水泵，电池供电，目标使用30天，预算90元。只做需求分析和至少两种候选方案，不采购、不接电、不运行硬件。'),
 ('counter','桌面按键计数器，短按加一，长按3秒清零，断电保存计数，USB供电，四位数显示，预算60元。只做需求分析和至少两种候选方案，不采购、不接电、不运行硬件。')]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true');parser.add_argument('--seed',type=int,default=20261021);args=parser.parse_args()
    if not args.live:raise SystemExit('--live is required; uses the existing daily budget')
    model=LocalSettings(ROOT).model()
    if model is None:raise SystemExit('model not configured')
    selected=random.Random(args.seed).sample(POOL,3)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    folder=ROOT/'runtime/scenario-tests'/stamp;folder.mkdir(parents=True)
    before=model.budget.status()['accounted_cny'];rows=[]
    for name,description in selected:
        fixture=ArchitectureTests();fixture.setUp();row={'case':name,'description':description,'trace':[]}
        try:
            service=EngineeringService(fixture.root);p=service.create(description);control=DecisionController(service)
            run=control.create(p['id'],max_steps=5,max_repairs=0,scope='documentation_only');runner=AutonomousRunner(control,ModelDecider(model))
            for _ in range(5):
                result=runner.step(run['id']);row['trace'].append({'status':result['status'],'message':result['message']})
                current=service.get(p['id'])
                if current['artifacts'].get('requirements') or result['status']!='continue':break
            current=service.get(p['id']);a=current['artifacts'];saved=control.load(run['id'])
            row.update(passed=bool(a.get('requirements',{}).get('requirements')) and len(a.get('comparison',{}).get('candidates',[]))>=2 and current['verification']['hardware']=='not_run',
                project_status=current['status'],requirements=len(a.get('requirements',{}).get('requirements',[])),candidates=len(a.get('comparison',{}).get('candidates',[])),
                scope='live_model_analysis_only_no_hardware_no_implementation',project=current,run=saved)
        except Exception as exc:
            row.update(passed=False,error_type=type(exc).__name__,error=str(exc)[:500])
        finally:fixture.tearDown()
        rows.append(row);(folder/(name+'.json')).write_text(json.dumps(row,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in row.items() if k not in ('project','run','trace','description')},ensure_ascii=False),flush=True)
        if model.budget.status()['paused']:break
    report={'seed':args.seed,'cases':[{'case':r['case'],'passed':r['passed'],'requirements':r.get('requirements'),'candidates':r.get('candidates'),'scope':r.get('scope'),'trace':r['trace']} for r in rows],
        'accounted_cost_cny':model.budget.status()['accounted_cny']-before,'all_passed':len(rows)==3 and all(r['passed'] for r in rows),
        'limitation':'Only new requirement analysis and candidate generation were exercised. Not an end-to-end firmware or hardware acceptance.'}
    (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
