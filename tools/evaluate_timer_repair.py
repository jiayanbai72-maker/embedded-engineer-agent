"""One isolated paid timer repair evaluation. Original assertions are frozen."""
from pathlib import Path
import argparse,json,hashlib
from embedded_agent.local_model import LocalSettings
from embedded_agent.draft_verification import verify
from embedded_agent.repair_coach import brief
parser=argparse.ArgumentParser();parser.add_argument('--run-paid',action='store_true');args=parser.parse_args()
if not args.run_paid:raise SystemExit('No model call; --run-paid requires authorization')
root=Path(__file__).resolve().parents[1];settings=LocalSettings(root);before=settings.budget.status()
if before['paused']:raise SystemExit('Budget paused; not reset')
header='#include <stdint.h>\nstruct Clock { uint32_t total_start,phase_start; int phase; }; void begin(struct Clock *c,uint32_t now); void step(struct Clock *c,uint32_t now);\n'
source='#include "clock.h"\nvoid begin(struct Clock *c,uint32_t now){c->total_start=now;c->phase_start=now;c->phase=1;}\nvoid step(struct Clock *c,uint32_t now){ uint32_t elapsed=now-c->total_start; if(elapsed>=2000u){c->phase=4;return;} if(c->phase==1 && elapsed>=30u){c->phase=2;} else if(c->phase==2 && elapsed>=400u){c->phase=3;} else if(c->phase==3 && elapsed>=700u){c->phase=4;} }\n'
test='#include <assert.h>\n#include "clock.h"\nint main(void){struct Clock c; begin(&c,0);step(&c,29);assert(c.phase==1);step(&c,30);assert(c.phase==2);step(&c,429);assert(c.phase==2);step(&c,430);assert(c.phase==3);step(&c,729);assert(c.phase==3);step(&c,730);assert(c.phase==4);begin(&c,0xfffffff0u);step(&c,14);assert(c.phase==2);step(&c,413);assert(c.phase==2);step(&c,414);assert(c.phase==3);step(&c,714);assert(c.phase==4);begin(&c,0);step(&c,2000);assert(c.phase==4);return 0;}\n'
files={'clock.h':header,'clock.c':source,'test_clock.c':test};initial=verify(root,files,'Cortex-M0plus');assert initial['status']=='failed'
model=settings.model()
if model is None:raise SystemExit('No enabled model')
context={'scope':'isolated_timer_holdout','requirements':'阶段1等待30ms；阶段2从实际进入时刻保持400ms；阶段3再保持300ms；总超时2000ms优先进入阶段4；32位时钟回绕下差值仍正确。只改clock.c，保持接口与原断言。',
         'files':files,'verification':initial,'repair_coach':brief(files,initial),'sha256':hashlib.sha256(source.encode()).hexdigest()}
answer=model.generate(role='timer_repair_evaluation',instruction='根据真实测试与源码自行修复clock.c。只输出一个JSON对象：{file:"clock.c",sha256:原哈希,content:完整新源码,rationale:简短依据}。不改测试或头文件，不硬编码测试时间点。',context=context)
if answer.get('file')!='clock.c' or answer.get('sha256')!=context['sha256'] or not isinstance(answer.get('content'),str):raise ValueError('Invalid repair output; no retry')
fixed=dict(files);fixed['clock.c']=answer['content'];result=verify(root,fixed,'Cortex-M0plus');after=settings.budget.status()
report={'scope':'single_synthetic_timer_case_not_general_independence','passed':result['status']=='passed','model':model.model,'model_answer':answer,
        'original_failure':initial,'verification':result,'tests_unchanged':fixed['test_clock.c']==test,'model_calls':after['completed_calls']-before['completed_calls'],
        'cost_delta_cny':round(after['accounted_cny']-before['accounted_cny'],8)}
out=root/'runtime/draft-validation/timer-model-holdout.json';out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:report[k] for k in ('passed','tests_unchanged','model_calls','cost_delta_cny')},ensure_ascii=False))
