"""Deterministic model view; never edits persisted engineering evidence.

Keep current requirements, artifacts, contracts and recent tool results intact.
Remove duplicate receipt bodies and describe omitted history explicitly.
No extra model call is used for summarization.
"""
from copy import deepcopy
import hashlib
import json


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True).encode('utf-8')


def summary(value, fields):
    return {**{key: deepcopy(value[key]) for key in fields if key in value},
            'historical_summary': True, 'sha256': hashlib.sha256(encoded(value)).hexdigest()}


def prepare(context):
    if context.get('run',{}).get('scope')=='research_only':
        return research_view(context)
    view = deepcopy(context)
    from .analysis_quality import reference
    view['independent_analysis_reference'] = reference(context.get('project', {}).get('description', ''))
    before = len(encoded(context))
    run = view.get('run', {})
    observations = run.get('observations', [])
    # Retain complete recent observations, including source/hash/page evidence.
    # Receipt IDs remain usable for plan response_to validation.
    receipts = run.get('receipts', {})
    receipt_fields = ('action', 'status', 'project_revision', 'project_status', 'message')
    run['receipts'] = {key: summary(value, receipt_fields) for key, value in receipts.items()}
    run['observations'] = observations[-3:]
    run['observation_history'] = {'count': max(0, len(observations)-3), 'details': '历史回执索引见run.receipts，最近观察见run.observations'}
    if 'plan_history' in run:
        run['plan_history'] = [summary(value, ('version', 'goal', 'rationale', 'response_to')) for value in run['plan_history']]
    project = view.get('project', {})
    events = project.get('events', [])
    project['events'] = [summary(value, ('action', 'status', 'revision', 'message', 'timestamp')) for value in events[-5:]]
    artifacts = project.get('artifacts', {})
    loop = artifacts.get('design_loop', {})
    rounds = loop.get('rounds', [])
    if len(rounds) > 1:
        loop['rounds'] = rounds[-1:]
        loop['prior_rounds'] = [summary(value, ('number', 'source_revision', 'status'))
                                | {'objectives': deepcopy(value.get('plan', {}).get('objectives', []))}
                               for value in rounds[:-1]]
    # Design tools return snapshots of the full round. The latest snapshot is
    # already available once in project.artifacts.design_loop; don't send it
    # three more times. Never replace rejected feedback or read-source results.
    if rounds:
        current = rounds[-1]
        for receipt in run['observations']:
            result = receipt.get('tool_result')
            if (receipt.get('status') == 'executed' and receipt.get('action', '').startswith('design_')
                    and isinstance(result, dict) and result.get('round') == current.get('number')):
                receipt['tool_result'] = {
                    'round': result['round'], 'status_at_execution': result.get('status'),
                    'snapshot_sha256': hashlib.sha256(encoded(result)).hexdigest(),
                    'current_round_ref': 'project.artifacts.design_loop.rounds[-1]',
                    'note': '重复快照正文省略；当前完整计划、研究、检查及缺口在current_round_ref，执行时状态不代表当前状态。'}
    # Long human-facing guides duplicate the executable argument contracts.
    # Keep the contract authoritative; originals remain available on disk.
    guides = view.pop('engineering_guides', {})
    if guides:
        view['guide_index'] = {key: {'sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(),
                                      'note': '人类操作指南正文省略，动作格式以action_contracts为准'}
                               for key, text in guides.items()}
    view['context_window'] = {
        'policy': 'current_state_and_last_3_observations_with_duplicate_design_snapshots_referenced',
        'original_bytes': before,
        'omitted_event_count': max(0, len(events)-5),
        'older_observations_summarized': max(0, len(observations)-3),
        'duplicate_receipt_bodies_removed': len(receipts),
        'rules': '需求、约束、验收、用户回答、当前计划、契约保留；最近3条观察仅去掉重复设计快照，并指向当前完整轮次；错误、源码及原文读取结果不裁剪。历史摘要不是完整原文，不能据此猜测源码、参数或测试结果。',
    }
    if project.get('status') in ('draft_ready','draft_verification_failed','draft_verified'):
        # Source repair needs actual source/tests and tool logs, not past research
        # rounds or older draft contents. Persisted project history is untouched.
        keep=('requirements','selected_plan','preliminary_acceptance','engineering_draft','draft_verification','draft_regression','draft_test_suite','draft_validation_cpu')
        project['artifacts']={k:artifacts[k] for k in keep if k in artifacts}
        current_draft=project['artifacts'].get('engineering_draft',{})
        for stage in ('interfaces','circuit'):
            section=current_draft.get(stage)
            if section and 'files' in section:
                section['file_index']={n: {'sha256':hashlib.sha256(b.encode()).hexdigest(),'bytes':len(b.encode())} for n,b in section.pop('files').items()}
                section['note']='本轮只修应用源码与测试失败，接口/连接原文件保留在项目中，未据此宣称电气通过。'
        firmware=current_draft.get('firmware',{})
        files=firmware.get('files',{})
        firmware['files']={n:b for n,b in files.items() if n.endswith(('.c','.h'))}
        firmware['other_file_index']={n:hashlib.sha256(b.encode()).hexdigest() for n,b in files.items() if not n.endswith(('.c','.h'))}
        import re
        report=project['artifacts'].get('draft_verification',{})
        from .repair_coach import brief
        view['repair_coach']=brief(files,report)
        log=report.get('host_tests',{}).get('log','')
        if report.get('host_tests',{}).get('assertion_diagnostic'):
            view['assertion_diagnostic']=deepcopy(report['host_tests']['assertion_diagnostic'])
        match=re.search(r'file ([^,\r\n]+), line (\d+)',log)
        if match and match.group(1) in files:
            number=int(match.group(2));lines=files[match.group(1)].splitlines()
            view['debugging_focus']={'failed_file':match.group(1),'line':number,
                'test_excerpt':[str(i+1)+': '+lines[i] for i in range(max(0,number-4),min(len(lines),number+3))],
                'instruction':'以完整原测试为准，审查全部断言而非只修当前一行；测试不可删改。用draft_edit修应用源码，然后draft_verify。'}
        run['observations']=[summary(o,('action','status','message','project_status')) | {'details_ref':'project.artifacts.draft_verification' if o.get('action')=='draft_verify' else 'run.receipts'} for o in run.get('observations',[])]
        if run.get('auto_feedback',{}).get('source_sha256')==report.get('source_sha256') and report:
            run['auto_feedback']={'status':report.get('status'),'details_ref':'project.artifacts.draft_verification'}
        view['context_window']['repair_focus']='仅当前源码、完整测试、当前工具结果与需求；旧研究不参与源码修复。'
    view['context_window']['prepared_bytes'] = len(encoded(view))
    feedback = run.get('auto_feedback', {})
    if feedback.get('status') == 'budget_paused' and '200KB' in feedback.get('message', ''):
        feedback['historical_only'] = True
        feedback['instruction'] = '旧版上下文超限记录；本轮长度以context_window为准，不要求用户删资料。实际费用保护仍由请求前预算检查执行。'
    return view


def research_view(context):
    """A separate read-only evidence task never needs firmware or test history."""
    fields=('allowed_actions','action_contracts','online_research','document_tools','authority','limits','decision_protocol','task_contract','orchestration_state')
    view={k:deepcopy(context[k]) for k in fields if k in context}
    if 'limits' in view:view['limits'].pop('remaining_repairs',None)
    view['research_budget_rule']='取证消耗remaining_steps及每日费用；工程源码修复次数不适用于搜索、下载、读取和参数核对。remaining_steps>0仍可执行允许的取证工具。'
    view['registered_parameters']=deepcopy(context.get('registered_parameters',[]))
    view['registered_facts']=deepcopy(context.get('registered_facts',[]))
    if context.get('previous_research_report'):view['previous_research_report']=deepcopy(context['previous_research_report'])
    project=context['project'];artifacts=project.get('artifacts',{})
    current=artifacts.get('design_loop',{}).get('rounds',[])
    current=current[-1] if current else {}
    view['project']={k:deepcopy(project[k]) for k in ('id','revision','description','status') if k in project}
    view['project']['artifacts']={k:deepcopy(artifacts[k]) for k in ('requirements','selected_plan','preliminary_acceptance') if k in artifacts}
    view['research_focus']={
        'round':current.get('number'),'gaps':deepcopy(current.get('gaps',[])),
        'candidates':deepcopy(current.get('plan',{}).get('candidates',[])),
        'evaluations':deepcopy(current.get('evaluations',[])),
        'prior_queries':[summary(r,('task_id','query','status')) for r in current.get('research_results',[])],
        'rule':'仅补充证据，不重写工程；关键参数保留待核对状态。原文通过read_document_page按资料编号和物理页读取。'}
    run=context['run'];view['run']={k:deepcopy(run[k]) for k in ('id','revision','project_revision','status','scope','research_task','steps','max_steps','auto_errors','auto_feedback') if k in run}
    observations=run.get('observations',[])
    notebook={}
    for receipt in observations:
        page=receipt.get('tool_result',{}).get('page')
        if isinstance(page,dict) and page.get('document_id'):
            notebook[(page['document_id'],page.get('page'),page.get('source_view','text'))]=page
    view['reading_notebook']=[]
    for source in list(notebook.values())[-4:]:
        page=deepcopy(source)
        page['text']=page.get('text','')[:16000]
        page['text_truncated']=len(source.get('text',''))>16000
        page['quote_blocks']=[b for b in page.get('quote_blocks',[]) if b['text'] in page['text']]
        view['reading_notebook'].append(page)
    view['reading_notebook_rule']='复用最近读取的原文块，分页表格应结合前页标题和续表核对，不能凭记忆或仅关键词猜行列；截断内容不代表全文。'
    view['run']['observations']=[]
    for o in observations[:-1]:
        item=summary(o,('id','action','status','message'))
        tool=o.get('tool_result',{})
        item['tool_outcome']={k:deepcopy(tool[k]) for k in ('status','reason','message','result','attempted_fields','repair_instruction') if k in tool}
        view['run']['observations'].append(item)
    if observations or run.get('cached_observation'):
        latest=deepcopy(run.get('cached_observation') or observations[-1])
        if run.get('cached_observation'):latest['cache_note']='复用已执行回执，不是新执行；利用此原文登记或结束报告，勿重复读取。'
        # Retain at most two original excerpts from a research batch; explicit
        # metadata points the agent back to the full, hash-checked page tool.
        result=latest.get('tool_result',{}).get('research',{})
        if isinstance(result,dict) and 'original_pages' in result:
            pages=result['original_pages'];result['original_pages']=pages[:2]
            result['omitted_original_page_count']=max(0,len(pages)-2)
            for page in result['original_pages']:
                if len(page.get('text',''))>8000:
                    page['text']=page['text'][:8000];page['text_truncated']=True
            result['reading_rule']='截取部分不代表全文；需要后续内容时调用read_document_page，不猜测缺失内容。'
        view['run']['observations'].append(latest)
    view['context_window']={'policy':'research_only_without_firmware_or_build_history','original_bytes':len(encoded(context)),
        'omitted_artifacts':{k:{'sha256':hashlib.sha256(encoded(v)).hexdigest(),'bytes':len(encoded(v))} for k,v in artifacts.items() if k not in view['project']['artifacts']},
        'rules':'项目完整原件保留在本机；本轮仅取证，不需要源码、测试日志和旧交付正文。摘要不能当原文引用。'}
    view['context_window']['prepared_bytes']=len(encoded(view))
    return view
