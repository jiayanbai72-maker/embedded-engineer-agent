"""One model-facing protocol; deterministic metadata, no invented reasoning."""
from copy import deepcopy


PROTOCOL = {
    'version': 2,
    'act': {'action': '从allowed_actions选择', 'arguments': '按action_contracts填写对象', 'reason': '简短说明为何选择此动作'},
    'pause': {'kind': 'pause', 'reason': '说明缺什么、已做什么、需要的外部条件'},
    'plan': {'kind': 'plan', 'plan': {'goal': '目标', 'reason': '规划依据',
                                    'tasks': [{'action': '工具名', 'title': '任务说明'}]}},
    'rules': ['普通动作无需生成kind、source、expected或UUID。',
              '任务身份仅在能唯一对应ready任务时由程序补齐，多个同类任务必须明确选择。',
              '简化计划按列表顺序建立依赖及真实完成条件；高级计划仍支持显式依赖。',
              '研究任务编号、观察编号和执行回执摘要是不同命名空间；使用runtime_frame中的可用项。']}


def normalize(answer, context):
    if not isinstance(answer, dict): raise ValueError('response: 需要JSON对象')
    result = deepcopy(answer)
    kind = result.get('kind')
    if kind == 'pause': return result
    if kind == 'plan':
        plan = result.get('plan')
        if not isinstance(plan, dict): raise ValueError('plan: 需要对象')
        plan.setdefault('rationale', plan.get('reason'))
        plan.setdefault('source', 'configured_model')
        tasks = plan.get('tasks')
        if isinstance(tasks, list):
            prior = None
            for index, task in enumerate(tasks):
                if not isinstance(task, dict): continue
                task.setdefault('action', task.get('tool'))
                task.setdefault('id', 'task_'+str(index+1))
                task.setdefault('title', task.get('name', task.get('action')))
                task.setdefault('depends_on', [prior] if prior else [])
                completion = {'status': 'executed'}
                if task.get('action') in ('build','test','mcu_build','firmware_build','keil_build','draft_verify'):
                    completion['tool_result.status'] = 'passed'
                if task.get('action') == 'execute': completion['project_status'] = 'documents_delivered'
                task.setdefault('completion', completion)
                prior = task['id']
        return result
    if kind not in (None, 'decision', 'action', 'tool', 'tool_call'):
        raise ValueError('kind: 只支持decision、plan或pause；普通动作可省略kind')
    result['kind'] = 'decision'
    action = result.get('action'); args = result.get('arguments')
    if action not in context.get('allowed_actions', []): raise ValueError('action: '+str(action)+' 不在当前可执行动作范围；有效动作：'+','.join(context.get('allowed_actions', [])))
    if not isinstance(args, dict): raise ValueError('arguments: 需要对象')
    reason = result.get('rationale') or result.get('reason') or args.get('rationale')
    if not isinstance(reason, str) or not reason.strip(): raise ValueError('reason: 请提供简短决策依据')
    result['rationale'] = reason
    defaults = []
    schema=context.get('action_contracts',{}).get(action,{}).get('arguments_schema',{})
    if 'rationale' in schema.get('required',[]) and 'rationale' not in args:
        args['rationale']=reason
        defaults.append('arguments.rationale')
    if not isinstance(result.get('expected'), str) or not result['expected'].strip():
        result['expected'] = '执行 '+action+' 并记录实际结果；是否满足要求以真实回执为准'
        defaults.append('expected')
    if not result.get('task_id'):
        ready = [t for t in (context.get('task_progress') or {}).get('tasks', []) if t['status']=='ready' and t['action']==action]
        if len(ready) == 1: result['task_id'] = ready[0]['id']; defaults.append('task_id')
        elif len(ready) > 1: raise ValueError('task_id: 存在多个同类ready任务，请明确选择 '+','.join(t['id'] for t in ready))
    if defaults: result['metadata_defaults'] = defaults
    return result


def frame(context):
    project = context.get('project', {}); run = context.get('run', {})
    tasks = context.get('task_progress')
    if tasks:
        ready = [{'ref':'run-task:'+t['id'], 'task_id':t['id'], 'action':t['action'], 'title':t['title']}
                 for t in tasks['tasks'] if t['status']=='ready']
    else:
        ready = [{'ref':'research-task:'+t['id'], 'action':'design_research', 'arguments':{'task_id':t['id']},
                  'title':t['question']} for t in context.get('design_research_tasks', {}).get('pending', [])]
        if not ready and 'analysis' in context.get('allowed_actions',[]):
            ready=[{'ref':'stage:analysis','action':'analysis','title':'提交原需求分析和至少两个候选；引用analysis_reference_catalog中的真实知识卡编号'}]
    loop = project.get('artifacts', {}).get('design_loop', {}).get('rounds', [])
    gaps = loop[-1].get('gaps', []) if loop else []
    routes = []
    if loop and loop[-1].get('evaluations'):
        if 'design_recommend' in context.get('allowed_actions', []): routes.append('比较现有检查结果后做有依据的推荐；缺证据时只能条件式推荐')
        if 'power_estimate' in context.get('allowed_actions', []): routes.append('可按明确假设完成工程估算，不能标为实测或已审核参数')
        routes.append('若剩余证据依赖联网、报价或实物，而工具尚不可用，集中列出缺口后暂停，不重复同一检索')
    draft=project.get('artifacts',{}).get('engineering_draft',{})
    if draft.get('firmware'):
        import hashlib
        draft_files=draft['firmware']['files']
        hashes={n:hashlib.sha256(b.encode()).hexdigest() for n,b in draft_files.items() if n.endswith(('.c','.h'))}
    else: hashes={}
    if project.get('status') in ('draft_in_progress','draft_ready','draft_verified','draft_verification_failed'):
        routes=['已由用户选择初步方案。复用已有证据，不再为了未核价或未实测重启设计研究。下一步draft_artifacts阶段：'+str(draft.get('next_stage','interfaces'))+'；固件阶段必须含一个test_*.c行为测试入口与实际断言。三阶段后先draft_verify（CPU从所选芯片确定），读取工具日志；failed则修源码/测试再验，unsupported则说明缺少工具，不得标通过。仅draft_verified后execute打包。未知项标TBD并保留验收缺口，不得伪造硬件验证。']
    return {'version':2, 'project_status':project.get('status'), 'ready_work':ready,
            'remaining_steps':context.get('limits', {}).get('remaining_steps'),
            'last_error':{k:v for k,v in (run.get('auto_feedback') or {}).items() if k in ('status','message','action')},
            'evidence_gap_count':len(gaps), 'evidence_gaps_ref':'project.artifacts.design_loop.rounds[-1].gaps',
            'observation_ids':context.get('design_observation_catalog', {}).get('valid_ids', []),
            'draft_source_hashes':hashes,'plan_receipt_ids':list(run.get('receipts', {})), 'exit_routes':routes,
            'boundaries': {'hardware_verified':project.get('verification', {}).get('hardware')=='passed', 'web_search':context.get('online_research',{}).get('status','not_connected'), 'live_quotes':'not_connected'},
            'exit_policy':'资料缺口不能靠重复动作变成证据；可做明确标注的估算、条件式推荐或暂停说明缺少的外部条件。不得自行放宽需求或代替用户确认。'}
