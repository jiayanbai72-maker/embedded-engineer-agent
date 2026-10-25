"""Preserve measured assertion progress; never promote a failing candidate."""
from copy import deepcopy
import hashlib
import json
from .draft_verification import source_hash


def tests_hash(files):
    return hashlib.sha256(json.dumps({n:b for n,b in files.items() if n.startswith('test_') and n.endswith('.c')},sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def checkpoint(artifacts):
    draft=artifacts.get('engineering_draft',{});files=draft.get('firmware',{}).get('files',{})
    report=artifacts.get('draft_verification',{})
    if files and report.get('source_sha256')==source_hash(files):
        artifacts['draft_checkpoint']={'draft':deepcopy(draft),'verification':deepcopy(report),'tests_sha256':tests_hash(files)}


def preserve(artifacts,candidate):
    baseline=artifacts.get('draft_checkpoint');draft=artifacts['engineering_draft'];files=draft['firmware']['files']
    if not baseline or baseline['tests_sha256']!=tests_hash(files):return False
    previous=baseline['verification'];old=set(previous.get('host_tests',{}).get('passed_assertions',[]))
    current=set(candidate.get('host_tests',{}).get('passed_assertions',[]))
    known_failure=candidate.get('status')=='failed'
    lost=sorted(old-current)
    measured=candidate.get('host_tests',{}).get('assertion_progress_available',False)
    compile_failed=candidate.get('mcu_compile',{}).get('status')=='failed'
    if known_failure and ((old and lost and (measured or compile_failed)) or previous.get('status')=='passed'):
        artifacts.setdefault('draft_regression_history',[]).append({'candidate_draft':deepcopy(draft),'verification':deepcopy(candidate)})
        artifacts['draft_regression_history']=artifacts['draft_regression_history'][-3:]
        artifacts['draft_regression']={'status':'rolled_back','lost_passed_assertions':lost,'candidate_verification':deepcopy(candidate),
                                     'restored_source_sha256':previous.get('source_sha256'),
                                     'note':'原测试未改。候选丢失已观测通过断言或破坏通过版本，已恢复检查点；不宣称候选通过。'}
        artifacts['engineering_draft']=deepcopy(baseline['draft'])
        artifacts['draft_verification']=deepcopy(previous)
        return True
    artifacts.pop('draft_regression',None)
    return False
