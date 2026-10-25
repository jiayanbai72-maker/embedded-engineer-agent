"""Run local unittest curriculum. Never contacts a model or hardware."""
import io
import json
import sys
import unittest
from datetime import datetime,timezone
from pathlib import Path
from embedded_agent.offline_curriculum import STAGES,fingerprint

root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root/'tests'))
report={'schema_version':1,'code_sha256':fingerprint(root),'created_at':datetime.now(timezone.utc).isoformat(),
        'scope':'offline_tool_regressions_not_model_training','model_calls':0,'hardware':'not_run','stages':[]}
for key,title,modules in STAGES:
    suite=unittest.defaultTestLoader.loadTestsFromNames(modules);output=io.StringIO()
    result=unittest.TextTestRunner(stream=output,verbosity=1).run(suite)
    row={'id':key,'title':title,'status':'passed' if result.wasSuccessful() else 'failed','tests':result.testsRun,
         'skipped':len(result.skipped),'failures':len(result.failures),'errors':len(result.errors),'log':output.getvalue()}
    report['stages'].append(row);print(title,row['status'],row['tests'],flush=True)
report['status']='passed' if all(x['status']=='passed' for x in report['stages']) else 'failed'
folder=root/'runtime/offline-training';folder.mkdir(parents=True,exist_ok=True)
(folder/'latest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
(folder/'latest.md').write_text('# 无开发板阶段训练检查\n\n范围：本地软件回归，不调用模型或硬件，不证明模型通用独立能力。\n\n'+ '\n'.join('- '+x['title']+'：'+x['status']+'，'+str(x['tests'])+'项，跳过'+str(x['skipped'])+'项' for x in report['stages'])+'\n',encoding='utf-8')
raise SystemExit(0 if report['status']=='passed' else 1)
