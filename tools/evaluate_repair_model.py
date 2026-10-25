"""One paid, isolated repair evaluation; no retry and no changes to user projects."""
import argparse
import hashlib
import json
from pathlib import Path
from embedded_agent.local_model import LocalSettings
from embedded_agent.draft_verification import verify
from embedded_agent.repair_coach import brief

parser=argparse.ArgumentParser();parser.add_argument('--run-paid',action='store_true');args=parser.parse_args()
if not args.run_paid:raise SystemExit('No model call. Pass --run-paid only when authorized.')
root=Path(__file__).resolve().parents[1];settings=LocalSettings(root);before=settings.budget.status()
if before['paused']:raise SystemExit('Daily budget paused; not reset.')
header='struct Port { void (*send)(int); int selected; int lanes; }; void perform(struct Port *p);\n'
source='#include "port.h"\nstatic void return_group(struct Port *p) { int k; for(k=0;k<p->lanes;k++) p->send(k); }\nvoid perform(struct Port *p) { p->send(p->selected); return_group(p); }\n'
test='#include <assert.h>\n#include "port.h"\nstatic int sends,last;\nstatic void observe(int channel) { sends++; last=channel; }\nint main(void) { struct Port p={observe,3,5}; perform(&p); assert(sends==2&&last==3); sends=0; p.selected=0; perform(&p); assert(sends==2&&last==0); return 0; }\n'
files={'port.h':header,'port.c':source,'test_port.c':test}
initial=verify(root,files,'Cortex-M0plus');assert initial['status']=='failed'
context={'scope':'isolated_synthetic_holdout_not_user_project','requirements':'一次操作仅对selected通道输出移动、回中两次；其他通道不能收到输出。不同selected都应满足。不得改测试、头文件或接口。',
         'files':files,'verification':initial,'repair_coach':brief(files,initial),
         'file_sha256':hashlib.sha256(source.encode()).hexdigest()}
model=settings.model()
if model is None:raise SystemExit('No model configured; no call')
answer=model.generate(role='repair_evaluation',instruction='根据给定源码、真实失败和调用追踪修复port.c。只输出单个JSON对象：{file:"port.c",sha256:当前哈希,content:完整修复后的port.c,rationale:简短诊断依据}。不要改测试、头文件或计数器，不输出围栏。只给模型自己修复，不复述案例答案。',context=context)
if answer.get('file')!='port.c' or answer.get('sha256')!=context['file_sha256'] or not isinstance(answer.get('content'),str):raise ValueError('Evaluation output invalid; no retry')
fixed=dict(files);fixed['port.c']=answer['content'];result=verify(root,fixed,'Cortex-M0plus');after=settings.budget.status()
report={'scope':'single_synthetic_holdout_not_general_independence','model':model.model,'passed':result['status']=='passed',
        'original_failure':initial,'model_answer':answer,'verification':result,'tests_unchanged':fixed['test_port.c']==test,
        'cost_delta_cny':round(after['accounted_cny']-before['accounted_cny'],8),'model_calls':after['completed_calls']-before['completed_calls']}
output=root/'runtime/draft-validation/repair-model-holdout.json';output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'passed':report['passed'],'model_calls':report['model_calls'],'cost_cny':report['cost_delta_cny'],'tests_unchanged':report['tests_unchanged'],'report':str(output)},ensure_ascii=False))
