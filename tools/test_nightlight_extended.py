"""Frozen independent C regressions and bounded Agent repairs; no hardware."""

import os
# Public helper: configure EMBEDDED_PROJECT_ID_1 before use.
import json
import hashlib
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tools')]
from embedded_agent.draft_verification import verify
from embedded_agent.local_model import LocalSettings
from embedded_agent.service import EngineeringService
from run_expanded_tests import Metered

EXTRA='''
static void trigger(void){nl_reset();nl_step(0,1,0);nl_step(200,1,0);assert(nl_duty()==50);}
int main(void){
 uint32_t t,r=73u;unsigned i;
 baseline_main();
 /* Continuous presence over one hour, followed by exact timeout. */
 trigger();for(t=1000;t<=3600000;t+=1000){nl_step(t,1,0);assert(nl_duty()==50);}
 nl_step(3629999,0,0);assert(nl_duty()==50);nl_step(3630000,0,0);assert(!nl_duty());
 /* A short high after any low must reconfirm; no timeout extension. */
 trigger();nl_step(201,0,0);nl_step(30000,1,0);nl_step(30001,0,0);nl_step(30200,0,0);assert(!nl_duty());
 /* A genuine reconfirmation near deadline extends it. */
 trigger();nl_step(201,0,0);nl_step(29999,1,0);nl_step(30199,1,0);nl_step(60198,0,0);assert(nl_duty()==50);nl_step(60199,0,0);assert(!nl_duty());
 /* Pressing brightness alone at expiry must not keep light on. */
 trigger();nl_step(30200,0,1);assert(!nl_duty());nl_step(30201,1,0);nl_step(30401,1,0);assert(nl_duty()==100);
 /* Button and confirmed motion in the same call. */
 nl_reset();nl_step(0,1,0);nl_step(200,1,1);assert(nl_duty()==100);
 /* Equal timestamps cannot manufacture 200ms confirmation. */
 nl_reset();for(i=0;i<1000;i++)nl_step(123,1,0);assert(!nl_duty());nl_step(323,1,0);assert(nl_duty()==50);
 /* Reset cancels active timeout and restores default brightness. */
 trigger();nl_step(201,1,1);nl_reset();assert(!nl_duty());nl_step(500,1,0);nl_step(700,1,0);assert(nl_duty()==50);
 /* 200 repeatable independently timed scenarios across uint32 wrap. */
 for(i=0;i<200;i++){r=r*1664525u+1013904223u;t=r;nl_reset();nl_step(t,1,0);nl_step(t+199u,1,0);assert(!nl_duty());nl_step(t+200u,1,0);assert(nl_duty()==50);nl_step(t+30199u,0,0);assert(nl_duty()==50);nl_step(t+30200u,0,0);assert(!nl_duty());}
 return 0;
}
'''

def main():
 folder=ROOT/'runtime/nightlight-c-repair';out=folder/'extended';out.mkdir(exist_ok=True)
 baseline=(folder/'test_nightlight.c').read_text(encoding='utf-8')
 tests=baseline.replace('int main(void)','static int baseline_main(void)',1)+EXTRA
 (out/'test_extended.c').write_text(tests,encoding='utf-8')
 files={n:(folder/n).read_text(encoding='utf-8') for n in ('nightlight.c','nightlight.h')}
 previous=json.loads((out/'report.json').read_text(encoding='utf-8')) if '--resume' in sys.argv else {};history=previous.get('history',[]);files=history[-1]['files'] if history else files;model=Metered(LocalSettings(ROOT).model())
 for turn in range(4):
  report=verify(ROOT,dict(files,**{'test_extended.c':tests}),'Cortex-M0plus')
  history.append({'status':report['status'],'report':report,'files':files})
  print('test',turn,report['status'],report['host_tests'].get('log','')[-1000:],flush=True)
  if report['status']=='passed':break
  if turn==3:break
  answer=model.generate(role='c_module_writer',instruction='根因已定位：低电平分支只清s_cand_active，却没有立即清s_motion_valid，所以下一次短高直接刷新s_last_act_ms。必须在每次motion为0时立即清s_motion_valid；关灯超时判断依据s_light_on而不是s_motion_valid，否则清有效态后又无法关灯。未确认高电平期间也须检查超时，只有重新确认满200ms才刷新last_act。不要只重排函数或复制旧逻辑。最小修复人体感应夜灯C99模块，返回完整nightlight.c/nightlight.h与rationale；原冻结测试和新增测试不能修改。默认亮度50，按键上升沿50->100->20->50，reset后首按为有效上升沿；感应高连续200ms确认；任何低采样必须撤销感应有效态/候选，灯光可继续延时；后续短高脉冲不能直接刷新延时，必须重新确认200ms。有效高刷新最后活动时刻；距最后有效活动满30000ms熄灯。使用uint32模差。勿保留宣称已实现但实际未使用的按键最大时长配置。不得引入芯片驱动、虚构原厂数据或改变API。实际失败日志与当前源码见输入。',context={'current_files':files,'frozen_tests':tests,'actual_result':report})
  (out/f'agent-{len(history)}.json').write_text(json.dumps(answer,ensure_ascii=False,indent=2),encoding='utf-8')
  if set(answer.get('files',{}))!={'nightlight.c','nightlight.h'}:raise ValueError('Unexpected files')
  files=answer['files']
 calls=previous.get('calls',[])+model.calls
 summary={'status':history[-1]['status'],'history':history,'calls':calls,'cost_cny':sum(c['accounted_cny'] for c in calls),'baseline_sha256':hashlib.sha256(baseline.encode()).hexdigest(),'extended_sha256':hashlib.sha256(tests.encode()).hexdigest(),'hardware':'not_run'}
 if summary['status']=='passed':
  service=EngineeringService(ROOT);pid=os.environ['EMBEDDED_PROJECT_ID_1'];p=service.get(pid)
  p=service.update(pid,p['revision'],'implementation_scope',{'confirmed':True,'mode':'mcu_compile'})
  p=service.update(pid,p['revision'],'mcu_implementation',{'files':dict(files,**{'test_nightlight.c':baseline,'test_extended.c':tests}),'cpu':'Cortex-M0plus','rationale':'Agent依据新增冻结测试修正连续确认状态；原测试保留，扩展主机断言与目标内核编译通过，硬件未运行'})
  p=service.update(pid,p['revision'],'mcu_build',{})
  if p['artifacts']['mcu_build']['status']!='passed':raise ValueError('Project MCU build did not pass')
  p=service.update(pid,p['revision'],'execute',{});(out/'夜灯C模块扩展测试交付包.zip').write_bytes(service.download(pid))
  for n,s in files.items():(folder/n).write_text(s,encoding='utf-8')
  summary['project_revision']=p['revision']
 (out/'report.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({k:v for k,v in summary.items() if k not in ('history','calls')},ensure_ascii=False))

if __name__=='__main__':main()
