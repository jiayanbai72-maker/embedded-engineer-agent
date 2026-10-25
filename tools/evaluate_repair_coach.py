"""Offline tool/case evaluation. Does NOT measure the model's repair success rate."""
from pathlib import Path
import json
from embedded_agent.draft_verification import verify
from embedded_agent.repair_coach import function_index

root=Path(__file__).resolve().parents[1]
results=[]
for helper,count in [('fanout_reset',3),('broadcast_lane',5)]:
    source='struct Bus { void (*write)(int); };\nstatic void '+helper+'(struct Bus *b) { int i; for(i=0;i<'+str(count)+';i++) b->write(i); }\nvoid issue(struct Bus *b) { b->write(0); '+helper+'(b); }\n'
    header='struct Bus { void (*write)(int); }; void issue(struct Bus *b);\n'
    test='#include <assert.h>\n#include "case.h"\nstatic int writes;\nstatic void output(int lane) { (void)lane; writes++; }\nint main(void) { struct Bus b={output}; issue(&b); assert(writes==2); return 0; }\n'
    files={'case.c':source,'case.h':header,'test_case.c':test}
    bad=verify(root,files,'Cortex-M0plus');diag=bad['host_tests'].get('assertion_diagnostic',{})
    assert bad['status']=='failed' and diag.get('actual_values',{}).get('writes')==count+1
    trace=diag.get('call_trace',[])
    assert any(x['caller']==helper and x['count']==count for x in trace)
    fixed=dict(files);fixed['case.c']=source.replace('i<'+str(count),'i<1')
    good=verify(root,fixed,'Cortex-M0plus')
    assert good['status']=='passed'
    results.append({'case':helper,'scope':'synthetic_tool_evaluation_not_model_training',
                    'bug_verdict':bad['status'],'actual_writes':diag['actual_values']['writes'],
                    'trace':trace,'known_fixture_correction_verdict':good['status'],
                    'model_called':False,'test_unchanged':fixed['test_case.c']==files['test_case.c']})
output=root/'runtime/draft-validation/repair-coach-evaluation.json';output.parent.mkdir(parents=True,exist_ok=True)
output.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'cases':len(results),'tool_checks':'passed','model_called':False,'report':str(output)},ensure_ascii=False))
