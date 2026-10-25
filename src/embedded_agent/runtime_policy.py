"""Mechanical repeat protection; not a substitute for engineering judgement."""
import hashlib
import json


def signature(control, context, action, arguments, task_id=None):
    if action not in ('search_documents','research_documents','fetch_document','read_document_page','read_parameter','design_evaluate','power_estimate','draft_verify'):
        return None
    documents = control.service.app.documents
    index = documents.db
    epoch = (index.stat().st_mtime_ns, index.stat().st_size) if index.exists() else None
    state = {'index':epoch, 'task_id':task_id}
    if action in ('research_documents','fetch_document'):
        # Provider settings changes may justify a fresh action, but matching
        # results remain deduplicated by the research service itself.
        state['online_policy']=control.service.web.settings()
    if action == 'read_document_page':
        # Validate actual source integrity before declaring the request repeated.
        doc = documents.document(arguments.get('document_id'))
        state['source'] = (doc['sha256'], doc['text_sha256'])
    if action in ('read_parameter','design_evaluate'):
        folder = control.service.root/'runtime/knowledge/parameters'
        state['parameters'] = [(p.name, hashlib.sha256(p.read_bytes()).hexdigest()) for p in sorted(folder.glob('*.json'))]
    if action in ('design_evaluate','power_estimate'):
        artifacts = context['project']['artifacts']
        rounds = artifacts.get('design_loop', {}).get('rounds', [])
        state['design'] = {'plan':rounds[-1]['plan'], 'research':rounds[-1]['research_results']} if rounds else artifacts.get('selected_plan')
        state['requirements'] = artifacts.get('requirements')
    if action=='draft_verify':
        from .draft_verification import source_hash
        state['sources']=source_hash(context['project']['artifacts']['engineering_draft']['firmware']['files'])
    payload = {'action':action, 'arguments':arguments, 'state':state}
    return hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def repeated(run, work_key):
    if not work_key: return False
    return any(r.get('work_signature') == work_key and r.get('status') == 'executed'
               for r in run.get('receipts', {}).values())


REASON_LABELS = {'step_limit':'本轮步骤额度已用完', 'model_turn_limit':'本轮模型调用次数已用完',
                 'validation_limit':'连续校验失败，停止继续花费', 'budget_paused':'费用保护已暂停',
                 'confirmation_required':'等待用户确认', 'repeated_work':'检测到重复工作',
                 'model_pause':'模型说明需要暂停', 'runtime_state':'当前运行状态需要处理',
                 'model_not_connected':'模型尚未启用', 'continue':'正在推进', 'paused':'已暂停'}


def diagnostic_stall(run):
    """Two different source revisions produce identical measured assertion failures."""
    import json
    failures=[]
    for receipt in run.get('observations',[]):
        if receipt.get('action')!='draft_verify' or receipt.get('status')!='executed':continue
        result=receipt.get('tool_result',{})
        if result.get('status')=='passed':failures=[];continue
        diagnostic=result.get('host_tests',{}).get('assertion_diagnostic',{})
        if not diagnostic.get('actual_values'):
            failures=[]
            continue
        key=json.dumps({k:diagnostic.get(k) for k in ('file','expression','actual_values')},sort_keys=True)
        failures.append((key,result.get('source_sha256')))
    if len(failures)<2:return False
    return failures[-1][0]==failures[-2][0] and bool(failures[-1][1]) and failures[-1][1]!=failures[-2][1]
