"""Real local regression guard proof, no model and no user project mutation."""
import json
from pathlib import Path
from embedded_agent.draft_verification import verify
from embedded_agent.draft_regression import checkpoint,preserve
root=Path(__file__).resolve().parents[1]
header='int first(void); int second(void);\n'
test='#include <assert.h>\n#include "unit.h"\nint main(void) {\n int a=first();\n assert(a==1);\n { int b=second();\n assert(b==1); }\n return 0;\n}\n'
files={'unit.h':header,'unit.c':'int first(void){return 1;} int second(void){return 0;}','test_unit.c':test}
report=verify(root,files,'Cortex-M0plus');assert report['host_tests'].get('passed_assertions')==['test_unit.c#1']
a={'engineering_draft':{'firmware':{'files':dict(files)}},'draft_verification':report};checkpoint(a)
a['engineering_draft']['firmware']['files']['unit.c']='int first(void){return 0;} int second(void){return 1;}'
bad=verify(root,a['engineering_draft']['firmware']['files'],'Cortex-M0plus')
assert preserve(a,bad)
assert a['engineering_draft']['firmware']['files']==files
out={'scope':'synthetic_real_tool_regression_check','baseline_passed_assertions':report['host_tests']['passed_assertions'],
     'candidate_passed_assertions':bad['host_tests'].get('passed_assertions'), 'automatic_restore':True,'original_test_unchanged':a['engineering_draft']['firmware']['files']['test_unit.c']==test,'model_calls':0}
(root/'runtime/draft-validation/regression-guard-proof.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(out))
