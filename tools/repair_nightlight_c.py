"""Let the configured Agent implement a C nightlight module against frozen tests."""

import os
# Public helper: configure EMBEDDED_PROJECT_ID_1 before use.
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tools')]
from embedded_agent.local_model import LocalSettings
from embedded_agent.draft_verification import verify
from embedded_agent.service import EngineeringService
from run_expanded_tests import Metered

TEST='''#include <assert.h>
#include <stdint.h>
#include "nightlight.h"
static void on(uint32_t t){nl_reset();nl_step(t,1,0);nl_step(t+199u,1,0);assert(nl_duty()==0);nl_step(t+200u,1,0);assert(nl_duty()==50);}
int main(void){
 nl_reset();assert(nl_duty()==0);
 on(0);nl_step(201,0,0);nl_step(30199,0,0);assert(nl_duty()==50);nl_step(30200,0,0);assert(nl_duty()==0);
 nl_reset();nl_step(0,1,0);nl_step(100,0,0);nl_step(101,1,0);nl_step(300,1,0);assert(!nl_duty());nl_step(301,1,0);assert(nl_duty()==50);
 on(0);nl_step(20000,1,0);nl_step(49999,0,0);assert(nl_duty());nl_step(50000,0,0);assert(!nl_duty());
 on(0);nl_step(201,1,1);assert(nl_duty()==100);nl_step(202,1,1);assert(nl_duty()==100);nl_step(203,1,0);nl_step(204,1,1);assert(nl_duty()==20);
 nl_reset();nl_step(0,0,1);assert(!nl_duty());nl_step(1,1,0);nl_step(201,1,0);assert(nl_duty()==100);
 on(0xffffff00u);nl_step(0xffffffc9u,0,0);nl_step((0xffffffc8u+30000u),0,0);assert(!nl_duty());
 nl_reset();assert(!nl_duty());return 0;
}
'''

def main():
 folder=ROOT/'runtime/nightlight-c-repair';folder.mkdir(exist_ok=True)
 service=EngineeringService(ROOT);pid=os.environ['EMBEDDED_PROJECT_ID_1']
 project=service.get(pid);model=Metered(LocalSettings(ROOT).model());previous=json.loads((folder/'report.json').read_text(encoding='utf-8')) if '--resume' in sys.argv else {};history=previous.get('history',[])
 for turn in range(3):
  result=model.generate(role='c_module_writer',instruction='实现纯C99人体感应小夜灯模块，无硬件寄存器、无动态内存。返回nightlight.c/nightlight.h。API void nl_reset(void), void nl_step(uint32_t now_ms,uint8_t motion,uint8_t button), uint8_t nl_duty(void)。复位关灯、默认亮度50%；档位50->100->20->50；button上升沿仅切一档，持续按住不重复；nl_reset必须把上次button状态定义为0，因此复位后的首个button=1采样也算上升沿，不能用首采样初始化标志吞掉按键；关灯时切档记忆但不亮灯。motion高连续200ms才有效，毛刺归零；已有效时每个高采样刷新最后活动时刻；自最后有效活动起满30000ms关灯。uint32模差处理回绕，单次间隔小于2^31。nl_step首样本高可启动候选但不能立即点灯。所有默认数值是明确设计假设，不声称来自器件资料。只写模块，不能修改冻结测试。失败按实际日志修复。',context={'requirements':project['artifacts']['requirements'],'selected_plan':project['artifacts']['selected_plan'],'frozen_test':TEST,'previous_attempt':history[-1] if history else None})
  (folder/f'agent-{len(history)+1}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
  files=result.get('files',{})
  if set(files)!={'nightlight.c','nightlight.h'}:history.append({'status':'failed','reason':'Exactly nightlight.c/nightlight.h required'});continue
  files=dict(files,**{'test_nightlight.c':TEST});report=verify(ROOT,files,'Cortex-M0plus')
  history.append({'status':report['status'],'files':files,'report':report});print('attempt',turn+1,report['status'],report['host_tests'].get('log','')[-1800:],flush=True)
  if report['status']=='passed':break
 calls=previous.get('calls',[])+model.calls
 summary={'history':history,'calls':calls,'cost_cny':sum(c['accounted_cny'] for c in calls),'hardware':'not_run','status':history[-1]['status']}
 if summary['status']=='passed':
  (folder/'project-before.json').write_text(json.dumps(project,ensure_ascii=False,indent=2),encoding='utf-8')
  project=service.update(pid,project['revision'],'implementation_scope',{'confirmed':True,'mode':'mcu_compile'})
  project=service.update(pid,project['revision'],'mcu_implementation',{'files':files,'cpu':'Cortex-M0plus','rationale':'用户明确要求C语言；Agent编写模块已通过固定主机断言与Cortex-M0+编译，真实板级驱动和硬件仍未验证'})
  project=service.update(pid,project['revision'],'mcu_build',{})
  summary['project_revision']=project['revision'];summary['mcu_build']=project['artifacts']['mcu_build']['status']
 (folder/'report.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({k:v for k,v in summary.items() if k not in ('history','calls')},ensure_ascii=False))

if __name__=='__main__':main()
