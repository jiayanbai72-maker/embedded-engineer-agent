"""Persistent decide-act-observe controller; no built-in or simulated reasoning."""
import hashlib
import json
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4
from .analysis import text
from .planning import validate as validate_plan, progress
from .readiness import assess, capabilities
from .contracts import describe, validate_shape, CONTRACTS, PLAN_SCHEMA
from .design import observation_ids
from .decision_protocol import PROTOCOL, frame

OPERATIONS = {'analysis', 'implementation', 'build', 'test', 'execute', 'mcu_implementation', 'mcu_build', 'firmware_implementation', 'firmware_build', 'selection_check'}
OPERATIONS.add('mcu_test')
DESIGN_STATES={'awaiting_selection','ready_delivery','documents_delivered','selection_needs_evidence','selection_failed','selection_checked','design_researching','design_needs_evidence','design_has_feasible','design_no_feasible','preliminary_design'}
READ_OPERATIONS = {'search_documents':'documents.search', 'read_document_page':'documents.page', 'read_parameter':'parameters.read', 'read_keil_source':'keil.source'}
READ_OPERATIONS['discover_hardware'] = 'hardware.discover'
READ_OPERATIONS.update({'research_documents':'documents.research','fetch_document':'documents.fetch'})
READ_OPERATIONS['record_parameter']='parameters.auto_review'
READ_OPERATIONS['record_fact']='facts.auto_review'
READ_OPERATIONS['conclude_research']='research.conclude'
STATES = {
    'mcu_test': {'ready_delivery','mcu_build_failed'},
    'selection_check': {'ready_delivery','documents_delivered','selection_needs_evidence','selection_failed','selection_checked'},
    'analysis': {'awaiting_analysis', 'needs_input'},
    'implementation': {'awaiting_implementation', 'build_failed', 'test_failed'},
    'build': {'ready_build'}, 'test': {'ready_test'}, 'execute': {'ready_delivery','preliminary_design'},
    'mcu_implementation': {'awaiting_mcu_implementation', 'mcu_build_failed'}, 'mcu_build': {'ready_mcu_build'},
    'firmware_implementation': {'awaiting_firmware_implementation', 'firmware_build_failed'}, 'firmware_build': {'ready_firmware_build'},
}
OPERATIONS.add('draft_artifacts')
STATES['draft_artifacts']={'draft_in_progress','draft_ready','draft_verification_failed','draft_verified'}
OPERATIONS.add('draft_patch')
STATES['draft_patch']={'draft_ready','draft_verification_failed','draft_verified'}
OPERATIONS.add('draft_edit')
STATES['draft_edit']={'draft_ready','draft_verification_failed','draft_verified'}
OPERATIONS.add('draft_verify')
STATES['draft_verify']={'draft_ready','draft_verification_failed'}
STATES['execute'].add('draft_verified')
for operation in ('design_plan','design_research','design_evaluate','design_recommend'):
    OPERATIONS.add(operation)
    STATES[operation]=DESIGN_STATES
OPERATIONS.add('power_estimate'); STATES['power_estimate']=DESIGN_STATES
OPERATIONS.update(('keil_build', 'keil_edit'))
STATES['keil_build'] = {'ready_keil_build', 'keil_build_failed'}
STATES['keil_edit'] = {'ready_keil_build', 'keil_build_failed', 'ready_delivery'}
OPERATIONS.add('hardware_capture')
STATES['hardware_capture'] = set().union(*STATES.values())


class DecisionProvider(Protocol):
    def decide(self, context: dict) -> dict | None: ...


class DecisionController:
    def __init__(self, service):
        self.service = service
        self.root = service.root / 'runtime' / 'control-runs'
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, run_id):
        if str(UUID(run_id)) != run_id:
            raise ValueError('运行ID不正确')
        return self.root / (run_id + '.json')

    def save(self, run):
        path = self.path(run['id'])
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(path)

    def load(self, run_id):
        return json.loads(self.path(run_id).read_text(encoding='utf-8'))

    def create(self, project_id, max_steps=20, max_repairs=3, scope=None, task=None, evidence_goal=None):
        if scope not in (None,'research_only','documentation_only'):raise ValueError('运行范围无效')
        if task not in (None,'pwm_review') or (task and scope!='research_only'):raise ValueError('专项任务范围无效')
        from .research_orchestration import validate_goal
        evidence_goal=validate_goal(evidence_goal)
        if evidence_goal and scope!='research_only':raise ValueError('取证目标仅适用于只读取证运行')
        if type(max_steps) is not int or not 1 <= max_steps <= 50 or type(max_repairs) is not int or not 0 <= max_repairs <= 5:
            raise ValueError('运行预算无效')
        project = self.service.get(project_id)
        run = {'id': str(uuid4()), 'project_id': project_id, 'revision': 0,
               'project_revision': project['revision'], 'status': 'awaiting_decision',
               'max_steps': max_steps, 'max_repairs': max_repairs, 'steps': 0, 'repairs': 0,
               'pending': None, 'receipts': {}, 'observations': []}
        if scope:run['scope']=scope
        if task:run['research_task']=task
        if evidence_goal:run['evidence_goal']=evidence_goal
        self.save(run)
        return run

    def context(self, run_id):
        run = self.load(run_id)
        project = self.service.get(run['project_id'])
        allowed = [action for action in sorted(OPERATIONS) if project['status'] in STATES[action]]
        rounds=project['artifacts'].get('design_loop',{}).get('rounds',[])
        round=rounds[-1] if rounds else None
        accepted=round is not None and round['status']=='accepted'
        enabled={'design_plan':project['artifacts'].get('requirements',{}).get('status')=='confirmed' and (not round or bool(round['evaluations'])),
                 'design_research':bool(round) and not accepted and len(round['research_results'])<len(round['plan']['tasks']),
                 'design_evaluate':bool(round) and not accepted and bool(round['research_results']),
                 'design_recommend':bool(round) and not accepted and bool(round['evaluations'])}
        allowed=[action for action in allowed if action not in enabled or enabled[action]]
        actions = allowed + list(READ_OPERATIONS) + ['ask'] + (['finish'] if project['status'] == 'documents_delivered' else [])
        if run.get('scope')=='documentation_only':
            actions=[a for a in actions if a in ('analysis','search_documents','research_documents','fetch_document','read_document_page','read_parameter','ask','execute','finish')]
        if not project['artifacts'].get('keil_project'):
            actions = [a for a in actions if a not in ('keil_edit', 'keil_build', 'read_keil_source')]
        if not project['artifacts'].get('hardware_binding'):
            actions = [a for a in actions if a != 'hardware_capture']
        task_report = progress(run, actions, project['revision'])
        if task_report and task_report['completed'] < task_report['total']:
            ready = {t['action'] for t in task_report['tasks'] if t['status'] == 'ready'}
            actions = [a for a in actions if a in ready or a == 'ask']
        if run.get('scope')=='research_only':
            actions=[a for a in actions if a in ('search_documents','read_document_page','read_parameter','research_documents','fetch_document','record_parameter','record_fact','finish','conclude_research')]
            # Ending read-only research does not announce engineering delivery.
            if 'finish' not in actions:actions.append('finish')
            if not any(o.get('action') in ('search_documents','research_documents','fetch_document','read_document_page') for o in run['observations']):
                actions=[a for a in actions if a!='finish']
        if run.get('research_task')=='pwm_review':
            actions=[a for a in actions if a!='finish']
            if run['steps']>=run['max_steps']-1 or run.get('force_research_conclusion'):actions=['conclude_research']
        else:actions=[a for a in actions if a!='conclude_research']
        if run.get('scope')=='research_only' and run.get('force_evidence_finish'):
            actions=['finish']
        if run.get('scope')=='research_only' and run.get('research_task')!='pwm_review' and run['steps']>=run['max_steps']-1 and run['observations']:
            actions=['finish']
        policy=getattr(self.service,'online_allowed_operations',None)
        if policy is not None:
            actions=[a for a in actions if a in policy or a in ('ask','finish','search_documents','read_document_page','read_parameter','record_parameter','record_fact')]
        context = {'run': run, 'project': project, 'task_progress': task_report, 'allowed_actions': actions,
                'online_research': {'status':'enabled_unverified' if self.service.web.settings()['enabled'] else 'not_connected',
                                    'domains':self.service.web.settings()['domains'],
                                    'tools':'research_documents先本地查；未命中或明确missing_field后受控联网，fetch_document只导入允许的原厂HTTPS URL。结果为未审核资料，不自动确认参数。'},
                'plan_contract': PLAN_SCHEMA,
                'action_contracts': describe(actions),
                'analysis_references': self.service.app.knowledge.search('需求')[:3] if 'analysis' in actions else [],
                'engineering_guides': {key: (self.service.root / 'docs' / file).read_text(encoding='utf-8')
                    for key, file, action in [('design','候选方案与反馈闭环.md','design_plan'), ('power','整机功耗估算与初步设计.md','power_estimate')]
                    if action in actions and (self.service.root / 'docs' / file).is_file()},
                'capability_status': capabilities(self.service.app), 'readiness': assess(project),
                'capabilities': ['knowledge.search', 'documents.search', 'documents.page', 'parameters.read', 'host.py_compile', 'host.unittest', 'documents.zip', 'mcu.armcc.compile_only_requires_local_config', 'firmware.armcc.demo_image_requires_local_config'],
                'document_tools': {'search':'POST /knowledge/search {query, limit?, document_id?}', 'page':'POST /knowledge/page {document_id, page}',
                                   'parameters':'GET /knowledge/parameters', 'review':'Agent使用record_parameter自行核对并登记，含原文/数值/单位检查及模型语义复核，不要求用户填表；搜索结果不直接当作参数证据'},
                'authority': 'confirm/select/design_accept 只能通过用户操作接口；decision 无权自行确认',
                'design_contract': {'plan':'design_plan {plan:{analyst,scope,rationale,objectives,candidates,tasks}}；调整需 changes、response_to，约束保持不变',
                                    'research':'design_research {task_id} 调用真实本地检索',
                                    'evaluate':'design_evaluate {} 检查全部候选并生成缺口',
                                    'recommend':'design_recommend {candidate_id,rationale,observation_ids}；未通过只能条件式推荐',
                                    'user_selection':'design_accept 仅用户操作，不是模型动作'},
                'limits': {'remaining_steps': run['max_steps'] - run['steps'], 'remaining_repairs': run['max_repairs'] - run['repairs']}}
        if round:
            ids = sorted(observation_ids(round))
            completed_research = {r['task_id'] for r in round['research_results']}
            pending_research = [t for t in round['plan']['tasks'] if t['id'] not in completed_research]
            context['design_research_tasks'] = {'round':round['number'], 'pending':pending_research,
                'completed_task_ids':sorted(completed_research),
                'rule':'检索任务编号来自pending[].id，和研究完成后产生的observation_id不同；观察编号为空不影响首次检索。'}
            research_contract = context['action_contracts'].get('design_research')
            if research_contract and pending_research:
                research_contract['arguments_schema']['properties']['task_id']['enum'] = [t['id'] for t in pending_research]
            context['design_observation_catalog'] = {'round': round['number'], 'valid_ids': ids,
                'rule': 'design_plan.response_to、changes[].observation_ids只使用这些编号；digest是执行回执摘要，不是观察编号。no_matches仅证明检索无命中，不证明器件参数。'}
            contract = context['action_contracts'].get('design_plan')
            if contract and ids:
                schema = contract['arguments_schema']['properties']['plan']['properties']
                schema['response_to']['items'] = {'type': 'string', 'enum': ids}
                schema['changes']['items']['properties']['observation_ids']['items'] = {'type': 'string', 'enum': ids}
        context['decision_protocol'] = PROTOCOL
        if 'analysis' in actions:
            if run.get('scope')=='documentation_only':
                context['action_contracts']['analysis']['arguments_schema']['properties']['decision']['properties']['actions']['enum']=[['export_documents']]
                context['execution_scope']='仅分析与文档交付，不生成源码，不编译，不运行或操作硬件。'
            ids=[r['id'] for r in context['analysis_references']]
            context['analysis_reference_catalog']={'valid_ids':ids,'rule':'analysis候选的evidence_ids引用这些真实知识卡ID；通用方法不证明芯片参数。不得用requirements等字段名冒充证据。'}
            candidate=context['action_contracts']['analysis']['arguments_schema']['properties']['comparison']['properties']['candidates']['items']['properties']
            if ids:
                candidate['evidence_ids']['items']={'type':'string','enum':ids}
                candidate['chip_options']['items']['properties']['evidence_ids']['items']={'type':'string','enum':ids}
        context['runtime_frame'] = frame(context)
        if run.get('research_task')=='pwm_review':
            for path in sorted(self.root.glob('*.json'),key=lambda p:p.stat().st_mtime_ns,reverse=True):
                prior=self.load(path.stem)
                if prior['id']!=run_id and prior['project_id']==run['project_id'] and prior.get('research_report'):
                    context['previous_research_report']={'run_id':prior['id'],'project_revision':prior['project_revision'],'report':{k:v for k,v in prior['research_report'].items() if k!='model_note'},
                        'rule':'上轮候选报告不是原始证据。旧模型说明已隔离；物理脚号以registered_facts中原厂表格行列核对结果pin_number为准，旧说明不能与原始证据并列当作两份冲突资料。'}
                    break
        if run.get('scope')=='research_only':
            context['registered_parameters']=[{k:p.get(k) for k in ('id','model','parameter','value','unit','conditions','document_id','page','valid','review_kind')} for p in self.service.app.parameters.list()]
            context['registered_facts']=[{k:p.get(k) for k in ('id','model','subject','predicate','object','conditions','document_id','page','valid','pin_number','source_view')} for p in self.service.app.parameters.facts()]
            from .research_orchestration import contract,recovery
            context['task_contract']=contract(run.get('research_task'),run.get('evidence_goal'))
            context['orchestration_state']=recovery(context)
        if policy is not None:
            context['execution_scope']='在线访客会话：可生成分析、源码和文档；当前无隔离执行器，不执行编译、生成代码测试或硬件操作。完成可独立生成的内容后明确结束，不反复请求不可用工具。用户可下载未验证草案。'
            context['capabilities']=[a for a in context['capabilities'] if not a.startswith(('host.','mcu.','firmware.'))]
        return context

    def close_completed_plan(self, run_id):
        context = self.context(run_id); run = context['run']; report = context['task_progress']
        # Keep the final delivery plan available until explicit finish records
        # completion. Only intermediate completed plans need automatic release.
        if context['project']['status'] == 'documents_delivered': return False
        if not report or not report['total'] or report['completed'] != report['total']:
            return False
        if run['status'] != 'awaiting_decision' or run.get('pending'): return False
        finished = run.pop('task_plan')
        run.setdefault('plan_history', []).append(finished)
        run['completed_plan'] = {'version': finished['version'], 'goal': finished['goal'],
                                 'completed': report['completed'], 'total': report['total'],
                                 'receipt_ids': [t['receipt_id'] for t in report['tasks']]}
        run['revision'] += 1
        # The old failure was only the lock to an already-completed plan.
        if run.get('auto_feedback', {}).get('message') == '决策必须关联当前可执行任务且动作一致':
            run['auto_errors'] = 0; run.pop('auto_feedback', None)
        self.save(run)
        return True

    def normalize_design_references(self, run_id, arguments):
        """Expand only exact, executed, current-round receipt aliases. Never guess."""
        from copy import deepcopy
        run = self.load(run_id)
        project = self.service.get(run['project_id'])
        rounds = project['artifacts'].get('design_loop', {}).get('rounds', [])
        if not rounds or not isinstance(arguments, dict): return arguments, []
        current = rounds[-1]; valid = observation_ids(current); aliases = {}
        for key, receipt in run['receipts'].items():
            result = receipt.get('tool_result')
            if receipt.get('status') != 'executed' or not receipt.get('action', '').startswith('design_') or not isinstance(result, dict) or result.get('round') != current['number']: continue
            available = sorted(observation_ids(result) & valid)
            if available:
                for alias in (key, receipt.get('digest')):
                    if alias: aliases[alias] = available
        result = deepcopy(arguments); plan = result.get('plan'); audit = []
        if not isinstance(plan, dict): return arguments, []
        def expand(refs):
            if not isinstance(refs, list): return refs
            expanded = []
            for ref in refs:
                replacement = aliases.get(ref) if isinstance(ref, str) and ref not in valid else None
                if replacement:
                    audit.append({'receipt_alias': ref, 'observation_ids': replacement, 'round': current['number']})
                    expanded.extend(replacement)
                else: expanded.append(ref)
            return list(dict.fromkeys(expanded)) if all(isinstance(v, str) for v in expanded) else expanded
        if 'response_to' in plan: plan['response_to'] = expand(plan['response_to'])
        for change in plan.get('changes', []) if isinstance(plan.get('changes'), list) else []:
            if isinstance(change, dict) and 'observation_ids' in change: change['observation_ids'] = expand(change['observation_ids'])
        return result, audit

    def reply(self, run_id, revision, message):
        run = self.load(run_id)
        if revision != run['revision'] or run['status'] not in ('waiting_input', 'awaiting_decision') or run['pending']:
            raise ValueError('当前运行没有等待用户回答，请刷新状态')
        project=self.service.get(run['project_id'])
        if project['revision'] != run['project_revision']:
            if project['status']!='awaiting_analysis':raise ValueError('项目已变化，请同步上下文后重新分析')
            run=self.refresh(run_id,run['revision'])
        if not isinstance(message, str) or not 0 < len(message.strip()) <= 4000:
            raise ValueError('回答需要1至4000个字符')
        messages = run.setdefault('user_messages', [])
        if len(messages) >= 30: raise ValueError('本轮回答数量达到上限，请新建运行')
        messages.append({'role': 'user', 'content': message.strip(), 'question': run.get('pause_question') or (run['observations'][-1].get('message', '用户追加说明') if run['observations'] else '用户追加说明'), 'project_revision': run['project_revision']})
        if run.get('diagnostic_stall_marker'):
            run['diagnostic_stall_ack']=run.pop('diagnostic_stall_marker')
        run.pop('pause_question', None)
        run['status'] = 'awaiting_decision'
        run['revision'] += 1
        self.save(run)
        return self.context(run_id)

    def plan(self, run_id, revision, proposal):
        run = self.load(run_id)
        if run.get('scope')=='research_only':raise ValueError('自主取证运行直接执行取证动作，不建立工程修改计划')
        if revision != run['revision'] or run['pending'] or run['status'] not in ('awaiting_decision', 'waiting_input'):
            raise ValueError('运行版本或状态不允许更新计划')
        if self.service.get(run['project_id'])['revision'] != run['project_revision']:
            raise ValueError('项目已变化，需要先刷新上下文')
        plan = validate_plan(proposal, OPERATIONS | set(READ_OPERATIONS))
        previous = run.get('task_plan')
        if previous:
            refs = proposal.get('response_to')
            if not isinstance(refs, list) or not refs or not all(isinstance(x, str) and x in run['receipts'] for x in refs):
                raise ValueError('调整计划需要引用真实执行回执编号')
            run.setdefault('plan_history', []).append(previous)
        plan['version'] = max([p['version'] for p in run.get('plan_history', [])] + ([previous['version']] if previous else [0])) + 1
        # A new version deliberately carries no completion claims from old tasks.
        run['task_plan'] = plan
        run['revision'] += 1
        self.save(run)
        return self.context(run_id)

    def submit(self, run_id, revision, decision):
        run = self.load(run_id)
        if not isinstance(decision, dict):
            raise ValueError('决策必须为对象')
        key = decision.get('id')
        if not text(key) or len(key) > 100:
            raise ValueError('决策需要唯一编号')
        digest = hashlib.sha256(json.dumps(decision, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        prior = run['receipts'].get(key)
        if prior:
            if prior['digest'] != digest:
                raise ValueError('同一决策ID不能更换内容')
            return run
        if run['pending']:
            if run['pending']['id'] == key and run['pending']['digest'] == digest:
                return run
            raise ValueError('尚有待执行决策')
        if type(revision) is not int or revision != run['revision'] or run['status'] != 'awaiting_decision':
            raise ValueError('运行版本或状态不允许提交')
        project = self.service.get(run['project_id'])
        if project['revision'] != run['project_revision'] or decision.get('project_revision') != project['revision']:
            raise ValueError('任务上下文已变化，需要刷新')
        action = decision.get('action')
        if action=='conclude_research' and run.get('research_task')!='pwm_review':raise ValueError('本轮不是PWM专项检查')
        if run.get('scope')=='research_only' and action not in self.context(run_id)['allowed_actions']:
            raise ValueError('本轮仅允许自主取证；先读取资料，保留项目与交付成果')
        if run.get('scope')=='documentation_only' and action not in self.context(run_id)['allowed_actions']:
            raise ValueError('本轮仅允许分析与文档交付，不允许源码实现、编译或硬件操作')
        if action not in OPERATIONS | set(READ_OPERATIONS) | {'ask', 'finish'}:
            raise ValueError('动作未授权或没有实现')
        for field in ('rationale', 'expected', 'source'):
            if not text(decision.get(field)): raise ValueError('decision.'+field+': 必须是非空字符串（外层字段，不是arguments内字段）')
        if not isinstance(decision.get('arguments'), dict): raise ValueError('decision.arguments: 必须是对象')
        if action in OPERATIONS and project['status'] not in STATES[action]:
            raise ValueError('动作前置条件未满足')
        if 'revision' in decision['arguments']:
            raise ValueError('项目版本由控制器设置')
        if action in CONTRACTS:
            validate_shape(CONTRACTS[action], decision['arguments'])
        if action=='analysis' and run.get('scope')=='documentation_only' and decision['arguments']['decision']['actions']!=['export_documents']:
            raise ValueError('documentation_only运行的decision.actions必须为[export_documents]，不得增加实现步骤')
        if action == 'ask' and not text(decision['arguments'].get('question')):
            raise ValueError('需要明确问题')
        if action == 'finish' and project['status'] != 'documents_delivered' and run.get('scope')!='research_only':
            raise ValueError('尚未交付，不能宣布完成')
        if run.get('task_plan') and action == 'finish':
            report = self.context(run_id)['task_progress']
            if report['completed'] != report['total']:
                raise ValueError('当前任务计划尚未全部完成')
        if run.get('task_plan') and action not in ('ask', 'finish'):
            tasks = self.context(run_id)['task_progress']['tasks']
            task = next((t for t in tasks if t['id'] == decision.get('task_id')), None)
            if not task or task['status'] != 'ready' or task['action'] != action:
                ready = [{'task_id':t['id'],'action':t['action']} for t in tasks if t['status']=='ready']
                raise ValueError('decision.task_id: 必须关联ready任务且action一致；提交编号='+str(decision.get('task_id'))+'；可执行任务='+json.dumps(ready,ensure_ascii=False))
            decision = dict(decision, plan_version=run['task_plan']['version'])
        # Validate resource limits before publishing the decision.
        if run['steps'] >= run['max_steps']:
            run['status'] = 'budget_exhausted'; run['revision'] += 1; self.save(run)
            raise ValueError('步骤预算耗尽')
        repairing = action in ('implementation', 'mcu_implementation', 'firmware_implementation', 'keil_edit', 'draft_artifacts', 'draft_edit', 'draft_patch') and project['status'] in ('build_failed', 'test_failed', 'mcu_build_failed', 'firmware_build_failed', 'keil_build_failed', 'draft_verification_failed')
        if repairing and run['repairs'] >= run['max_repairs']:
            run['status'] = 'repair_limit'; run['revision'] += 1; self.save(run)
            raise ValueError('修复次数达到上限，需要人工处理')
        run['pending'] = dict(decision, digest=digest, repairing=repairing)
        run['status'] = 'ready_action'
        run['revision'] += 1
        self.save(run)
        return run

    def observe(self, run, project, status, message='', tool_result=None):
        pending = run['pending']
        receipt = {'digest': pending['digest'], 'action': pending['action'], 'project_revision': project['revision'],
                   'status': status, 'message': message, 'project_status': project['status'], 'expected': pending['expected']}
        if pending.get('metadata_defaults'):
            receipt['metadata_defaults'] = pending['metadata_defaults']
        if pending.get('reference_normalizations'):
            receipt['reference_normalizations'] = pending['reference_normalizations']
        if pending.get('work_signature'):
            receipt['work_signature'] = pending['work_signature']
        if pending.get('task_id') and 'plan_version' in pending:
            receipt.update(task_id=pending['task_id'], plan_version=pending['plan_version'])
        if tool_result is not None:
            receipt['tool_result']=tool_result
        if pending['action'] in ('search_documents','research_documents','fetch_document','read_document_page','read_parameter','record_fact','record_parameter'):
            receipt['arguments_snapshot']={k:v for k,v in pending['arguments'].items() if k in ('document_id','page','source_view','quote_id','model','parameter','value','unit','subject','predicate','object','conditions','query','url')}
        if pending['action'] in ('build', 'test', 'mcu_build', 'firmware_build', 'keil_build') and status == 'executed':
            name = {'build': 'build', 'test': 'verification', 'mcu_build': 'mcu_build', 'firmware_build': 'firmware_build', 'keil_build': 'keil_build'}[pending['action']]
            receipt['tool_result'] = project['artifacts'].get(name)
        if pending['action'].startswith('design_') and status == 'executed':
            round=project['artifacts'].get('design_loop',{}).get('rounds',[{}])[-1]
            receipt['tool_result']={'round':round.get('number'),'status':round.get('status'),
                                    'research_results':round.get('research_results'), 'evaluations':round.get('evaluations'),
                                    'gaps':round.get('gaps'), 'recommendation':round.get('recommendation')}
        if pending['action']=='draft_verify' and status == 'executed':
            receipt['tool_result']=project['artifacts'].get('draft_last_check',project['artifacts'].get('draft_verification'))
        if pending['action']=='power_estimate' and status == 'executed':
            receipt['tool_result']=project['artifacts'].get('power_estimates',{}).get(pending['arguments'].get('candidate_id'),{}).get('report')
        if pending['action'] == 'hardware_capture' and status == 'executed':
            receipt['tool_result'] = project['artifacts'].get('hardware_captures', [])[-1]
        run['receipts'][pending['id']] = receipt
        run['observations'].append(receipt)
        if run.get('scope')=='research_only' and status=='executed':
            from .research_orchestration import progress as evidence_progress
            before=evidence_progress(dict(run,observations=run['observations'][:-1]))
            after=evidence_progress(run)
            if any(after[k]>before[k] for k in ('original_pages_read','verified_records')):
                run['repeat_recovery_count']=0
                run.pop('force_evidence_finish',None)
                run.pop('force_research_conclusion',None)
        run['steps'] += 1
        if pending['repairing'] and status == 'executed':
            run['repairs'] += 1
        run['project_revision'] = project['revision']
        run['pending'] = None
        run['status'] = 'awaiting_decision'
        run['revision'] += 1
        self.save(run)
        return run

    def advance(self, run_id):
        run = self.load(run_id)
        if run['status'] not in ('ready_action', 'executing'):
            return run
        pending = run['pending']
        project = self.service.get(run['project_id'])
        base = pending['project_revision']
        action = pending['action']
        if run['status'] == 'executing':
            # If service committed before process interruption, recover the observation without rerunning tools.
            matches = [e for e in project['events'] if e.get('action') == action and e.get('source_revision') == base]
            if project['revision'] == base + 1 and matches:
                return self.observe(run, project, 'executed', '从已提交的服务事件恢复结果，未重复执行')
            run['status'] = 'interrupted_unknown'
            run['revision'] += 1
            self.save(run)
            return run  # Do not blindly retry uncertain side effects.
        if project['revision'] != base:
            return self.observe(run, project, 'stale', '项目变化，原决策未执行')
        if action == 'ask':
            run = self.observe(run, project, 'waiting_input', pending['arguments']['question'])
            run['status'] = 'waiting_input'; run['revision'] += 1; self.save(run)
            return run
        if action == 'finish':
            if project['status'] != 'documents_delivered' and run.get('scope')!='research_only':
                return self.observe(run, project, 'rejected', '交付条件不满足')
            if run.get('scope')=='research_only':
                from .research_orchestration import completion
                run['evidence_completion']=completion(self.context(run_id))
            run = self.observe(run, project, 'finished')
            run['status'] = 'complete'; run['revision'] += 1; self.save(run)
            return run
        if action in READ_OPERATIONS:
            arguments = dict(pending['arguments'], project_id=run['project_id']) if action in ('read_keil_source','research_documents','fetch_document') else pending['arguments']
            try:result=self.service.app.tools.execute(READ_OPERATIONS[action],arguments)
            except Exception as exc:
                from .local_model import BudgetPaused
                if not isinstance(exc,BudgetPaused):raise
                self.observe(run,project,'rejected',str(exc),tool_result={'status':'budget_paused','message':str(exc),'unknown_request_not_replayed':True})
                raise
            run=self.observe(run,project,'executed' if result['status']=='passed' else 'rejected',tool_result=result)
            if action=='conclude_research' and result['status']=='passed':
                from .research_report import export
                result['report']['files']=export(self.service.root,run['id'],result['report'])
                run['research_report']=result['report'];run['status']='complete';run['revision']+=1;self.save(run)
            return run
        run['status'] = 'executing'; run['revision'] += 1; self.save(run)
        try:
            project = self.service.update(run['project_id'], base, action, pending['arguments'])
            return self.observe(run, project, 'executed')
        except (ValueError, KeyError, TypeError) as exc:
            message = str(exc)[:1000] if isinstance(exc, ValueError) else ('缺少字段：'+str(exc.args[0])[:100] if isinstance(exc, KeyError) and exc.args else '字段结构或类型不正确')
            feedback = {'status': 'validation_failed', 'action': action, 'message': message,
                        'exception_type': type(exc).__name__, 'schema_ref': 'action_contracts.'+action+'.arguments_schema',
                        'attempted_arguments': pending['arguments'],
                        'instruction': '按具体错误与当前契约修正参数；保持原需求约束。不要让用户填写内部JSON，不要原样重复提交。'}
            return self.observe(run, self.service.get(run['project_id']), 'rejected', message, tool_result=feedback)
        except Exception:
            run['status'] = 'interrupted_unknown'; run['revision'] += 1; self.save(run)
            return run

    def refresh(self, run_id, revision):
        run = self.load(run_id)
        if revision != run['revision'] or run['pending'] or run['status'] not in ('awaiting_decision', 'waiting_input'):
            raise ValueError('当前状态不能刷新')
        current_revision = self.service.get(run['project_id'])['revision']
        if current_revision != run['project_revision']:
            run.pop('pause_question', None)
        if current_revision != run['project_revision'] and run.get('task_plan'):
            run.setdefault('plan_history', []).append(run.pop('task_plan'))
        run['project_revision'] = current_revision
        run['status'] = 'awaiting_decision'; run['revision'] += 1
        self.save(run)
        return run

    def tick(self, run_id, provider: DecisionProvider | None = None):
        run = self.load(run_id)
        if run['status'] in ('ready_action', 'executing'):
            return self.advance(run_id)
        if run['status'] != 'awaiting_decision' or provider is None:
            return run
        decision = provider.decide(self.context(run_id))
        if decision is None:
            return run
        self.submit(run_id, run['revision'], decision)
        return self.advance(run_id)
