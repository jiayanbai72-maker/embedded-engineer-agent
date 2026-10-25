"""Analyst-authored options, real research/check observations, evidence-linked revision."""
from copy import deepcopy
import hashlib
import json
from .selection import evaluate_selection


def require_text(value,label):
    if not isinstance(value,str) or not 0<len(value.strip())<=6000: raise ValueError('需要'+label)


def items(value,label,minimum=1,maximum=12):
    if not isinstance(value,list) or not minimum<=len(value)<=maximum: raise ValueError(label+'数量不正确')
    if any(not isinstance(x,dict) for x in value): raise ValueError(label+'必须为对象列表')
    identities=[x.get('id') for x in value]
    if any(not isinstance(x,str) or not 0<len(x)<=60 for x in identities) or len(set(identities))!=len(identities):
        raise ValueError(label+'编号无效或重复')
    return value


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def observation_ids(round):
    return {r['observation_id'] for r in round['research_results']} | {
        c['observation_id'] for e in round.get('evaluations',[]) for c in e['report']['checks']}


def current(project):
    loop=project.artifacts.get('design_loop')
    if not loop: raise ValueError('需要先提交候选方案与研究计划')
    if loop['requirements_sha256']!=fingerprint(project.artifacts['requirements']):
        raise ValueError('需求已变化，请重建方案分析')
    return loop,loop['rounds'][-1]


def plan(project,payload):
    reqs=project.artifacts.get('requirements',{})
    if reqs.get('status')!='confirmed': raise ValueError('需要先由用户确认需求')
    plan=deepcopy(payload.get('plan'))
    if not isinstance(plan,dict): raise ValueError('需要 plan 对象')
    for key in ('analyst','scope','rationale'): require_text(plan.get(key),key)
    objectives=items(plan.get('objectives'),'约束目标')
    candidates=items(plan.get('candidates'),'候选方案',2,6)
    tasks=items(plan.get('tasks'),'研究任务',1,12)
    req_ids={r['id'] for r in reqs['requirements']}
    objective_map={o['id']:o for o in objectives}; candidate_ids={c['id'] for c in candidates}
    for objective_index, objective in enumerate(objectives):
        require_text(objective.get('description'),'目标说明')
        if objective.get('kind') not in ('budget','energy','voltage','resource'): raise ValueError('目标检查类型未实现')
        refs=objective.get('requirement_ids')
        if not isinstance(refs,list) or not refs or not set(refs)<=req_ids: raise ValueError('目标必须关联已有需求')
        fixed=objective.get('fixed_inputs')
        anchors={'budget':{'limit_cny'},'energy':{'hours'},'resource':{'required','resource'},'voltage':set()}[objective['kind']]
        if not isinstance(fixed,dict) or not anchors<=set(fixed): raise ValueError(f'arguments.plan.objectives[{objective_index}].fixed_inputs: 缺少冻结的需求约束值；必需字段为'+','.join(sorted(anchors)))
    for candidate in candidates:
        for key in ('name','architecture'): require_text(candidate.get(key),key)
        if not isinstance(candidate.get('covers'),list) or not candidate['covers'] or not set(candidate['covers'])<=req_ids:
            raise ValueError('候选方案必须关联已有功能需求')
        for key in ('tradeoffs','risks','assumptions'):
            if not isinstance(candidate.get(key),list) or not candidate[key]: raise ValueError('需要候选方案取舍、风险和假设')
            for value in candidate[key]: require_text(value,key)
        components=candidate.get('components')
        if not isinstance(components,list) or not components: raise ValueError('需要组件及待定项')
        for component in components:
            if not isinstance(component,dict): raise ValueError('组件格式不正确')
            require_text(component.get('role'),'组件作用')
            if component.get('model') is not None: require_text(component['model'],'型号')
        checks=items(candidate.get('proposal',{}).get('checks'),'候选检查',1,24)
        covered=set()
        for check in checks:
            objective=objective_map.get(check.get('objective_id'))
            if not objective or check.get('kind')!=objective['kind']: raise ValueError('检查与约束目标不匹配')
            inputs=check.get('inputs')
            if not isinstance(inputs,dict) or any(inputs.get(k)!=v for k,v in objective['fixed_inputs'].items()):
                raise ValueError('候选方案不能修改冻结的需求约束')
            covered.add(objective['id'])
        if covered!=set(objective_map): raise ValueError('每个候选必须检查全部声明约束，不能删除不利检查')
    for task in tasks:
        for key in ('question','query','why'): require_text(task.get(key),key)
        if len(task['query'])>300: raise ValueError('研究检索词过长')
        if not isinstance(task.get('candidate_ids'),list) or not task['candidate_ids'] or not set(task['candidate_ids'])<=candidate_ids:
            raise ValueError('研究任务必须关联候选方案')
    old=project.artifacts.get('design_loop')
    if old:
        loop,previous=current(project)
        if len(loop['rounds'])>=10: raise ValueError('达到10轮方案预算，需要重新明确需求')
        if not previous.get('evaluations'): raise ValueError('先检查上一轮，再依据结果调整')
        if objectives!=previous['plan']['objectives']: raise ValueError('arguments.plan.objectives: 调整方案不能放宽原约束；必须原样保留 project.artifacts.design_loop.rounds[-1].plan.objectives；修改需求需用户补充')
        refs=plan.get('response_to')
        if not isinstance(refs,list) or not refs or not set(refs)<=observation_ids(previous):
            raise ValueError('arguments.plan.response_to: 调整必须引用上一轮真实观察编号；有效编号为 '+','.join(sorted(observation_ids(previous))))
        changes=plan.get('changes')
        if not isinstance(changes,list) or not changes: raise ValueError('arguments.plan.changes: 需要说明调整内容和原因，包含candidate_id、reason、observation_ids')
        before={c['id']:c for c in previous['plan']['candidates']}
        after={c['id']:c for c in candidates}
        changed={cid for cid in set(before)|set(after) if fingerprint({k:before.get(cid,{}).get(k) for k in ('components','architecture','proposal')})!=fingerprint({k:after.get(cid,{}).get(k) for k in ('components','architecture','proposal')})}
        if not changed: raise ValueError('没有组件、架构或检查输入变化，不能只改理由重复提交')
        explained=set()
        for change in changes:
            if not isinstance(change,dict): raise ValueError('调整说明格式不正确')
            require_text(change.get('reason'),'调整原因')
            citations=change.get('observation_ids')
            if not isinstance(citations,list) or not citations or not set(citations)<=set(refs): raise ValueError('调整原因缺少有效观察引用')
            explained.add(change.get('candidate_id'))
        if not changed<=explained: raise ValueError('每个变更或移除的候选都需要解释')
        loop=deepcopy(loop)
    else:
        loop={'requirements_sha256':fingerprint(reqs),'rounds':[],'mode':'analyst_assisted',
              'limitations':['分析者提出候选并判断调整方向；服务不冒充自主推理。','检查只覆盖声明的数值约束，功能、机构、引脚复用和实机仍需验证。']}
    round={'number':len(loop['rounds'])+1,'source_revision':project.revision,'plan':plan,'research_results':[],
           'evaluations':[],'recommendation':None,'status':'research_pending'}
    loop['rounds'].append(round)
    return loop


def research(project,payload,library,researcher=None):
    loop,round=current(project)
    if round['status']=='accepted': raise ValueError('本轮已确认，需要提出有依据的新一轮调整')
    task=next((t for t in round['plan']['tasks'] if t['id']==payload.get('task_id')),None)
    if not task: raise ValueError('研究任务不存在')
    if any(r['task_id']==task['id'] for r in round['research_results']): raise ValueError('任务已检索，调整后可在下一轮重查')
    lookup=researcher(task['query']) if researcher else None
    matches=lookup['matches'] if lookup else library.search(task['query'],limit=3)
    result={'observation_id':f"R{round['number']}:{task['id']}",'task_id':task['id'],'query':task['query'],
            'candidate_ids':task['candidate_ids'],'matches':matches,
            'status':'references_found' if matches else 'no_matches','parameters_verified':False}
    if lookup:result['online_research']=lookup
    round['research_results'].append(result)
    round['status']='research_observed'
    if round['evaluations']: round.setdefault('evaluation_history',[]).append(deepcopy(round['evaluations']))
    round['evaluations']=[]; round['recommendation']=None; round['gaps']=[]
    return loop


def evaluate(project,resolver):
    loop,round=current(project)
    if round['status']=='accepted': raise ValueError('本轮已确认，需要提出有依据的新一轮调整')
    if not round['research_results']: raise ValueError('先执行研究任务，取得真实观察后再比较')
    evaluations=[]; gaps=[]
    if round['evaluations']: round.setdefault('evaluation_history',[]).append(deepcopy(round['evaluations']))
    round['evaluation_count']=round.get('evaluation_count',0)+1
    all_reqs={r['id'] for r in project.artifacts['requirements']['requirements']}
    for candidate in round['plan']['candidates']:
        report=evaluate_selection(candidate['proposal'],resolver=resolver)
        objective_by_check={c['id']:c['objective_id'] for c in candidate['proposal']['checks']}
        for check in report['checks']:
            check['observation_id']=f"E{round['number']}.{round['evaluation_count']}:{candidate['id']}:{check['id']}"
            check['objective_id']=objective_by_check[check['id']]
            if check['status']!='passed':
                gaps.append({'candidate_id':candidate['id'],'observation_id':check['observation_id'],
                    'objective_id':check['objective_id'],'status':check['status'],
                    'calculation_status':check['calculation_status'],'missing_inputs':check['missing_inputs'],
                    'binding_errors':check['binding_errors'],
                    'suggested_next':'调整方案或向用户说明冲突' if check['status']=='failed' else {
                        'budget':'补齐采购范围、型号、数量、含日期的真实报价与运费；不能用手册推断价格',
                        'energy':'明确电池方案，核验可用容量；取得整机监听与动作功耗，区分估算与实测',
                        'resource':'核对具体型号的资源数量、引脚映射与复用冲突；复用引脚数不代表并发通道数',
                        'voltage':'核对供电输出范围与器件推荐工作范围、单位及适用条件'}[check['kind']],
                    'note':'未审核输入导致的计算失败仅是情景风险，不证明实际器件不合格' if check['calculation_status']=='failed' and check['status']=='needs_evidence' else ''})
        uncovered=sorted(all_reqs-set(candidate['covers']))
        evaluations.append({'candidate_id':candidate['id'],'name':candidate['name'],'report':report,
                            'uncovered_requirements':uncovered,
                            'eligible':report['status']=='passed' and not uncovered})
    round.update(evaluations=evaluations,gaps=gaps,recommendation=None,
                 status='constraints_feasible' if any(e['eligible'] for e in evaluations) else 'needs_evidence' if any(e['report']['status']=='needs_evidence' for e in evaluations) else 'no_feasible_option')
    return loop


def recommend(project,payload):
    loop,round=current(project)
    if round['status']=='accepted': raise ValueError('本轮已确认，不能回写推荐')
    result=next((e for e in round['evaluations'] if e['candidate_id']==payload.get('candidate_id')),None)
    if not result: raise ValueError('需要先检查候选方案')
    require_text(payload.get('rationale'),'推荐理由')
    refs=payload.get('observation_ids')
    if not isinstance(refs,list) or not refs or not set(refs)<=observation_ids(round): raise ValueError('推荐需引用本轮真实观察')
    if result['report']['status']=='failed': raise ValueError('已确认不满足约束的候选不能推荐；先调整方案')
    round['recommendation']={'candidate_id':result['candidate_id'],'rationale':payload['rationale'],
        'observation_ids':refs,'status':'constraints_checked' if result['eligible'] else 'conditional',
        'analyst':round['plan']['analyst'],'final_selection':False}
    return loop


def accept(project,payload,resolver):
    loop,round=current(project)
    if payload.get('confirmed') is not True: raise ValueError('需要用户明确选择方案')
    candidate=next((c for c in round['plan']['candidates'] if c['id']==payload.get('candidate_id')),None)
    if not candidate or not round['evaluations']: raise ValueError('候选不存在或尚未检查')
    report=evaluate_selection(candidate['proposal'],resolver=resolver)
    req_ids={r['id'] for r in project.artifacts['requirements']['requirements']}
    if report['status']!='passed' or not req_ids<=set(candidate['covers']): raise ValueError('证据或声明约束尚未满足，不能确认通过')
    round['status']='accepted'; round['accepted_candidate']=candidate['id']
    return candidate,report
