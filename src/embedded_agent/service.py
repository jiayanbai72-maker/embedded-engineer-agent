"""Local analyst-assisted agent service; decisions are supplied, never simulated."""
import hashlib
import base64
import io
import json
from zipfile import ZipFile, ZIP_DEFLATED
from .application import Application
from .analysis import validate_requirements, validate_comparison, text, strings
from .host import validate_files, run_host
from .mcu import validate_sources, compile_project
from .firmware import validate_profile, build_firmware
from .selection import evaluate_selection
from . import draft_regression
from . import draft_verification
from . import test_suites
from . import draft
from . import design
from .power import evaluate_power
from .readiness import assess
from . import keil
from . import hardware


class EngineeringService:
    def __init__(self, root):
        self.root = root
        self.settings_factory = None
        self.online_allowed_operations = None
        self.app = Application(root)
        from .online_research import OnlineResearch
        self.web=OnlineResearch(root,self.app.documents)
        self.app.online_research=self.web
        self.app.tools.register('documents.research',lambda args:dict(status='passed',research=self.web.autonomous_research(args['project_id'],args['query'],args.get('missing_field'))),lambda args:None)
        def auto_parameter(args):
            from .local_model import LocalSettings, BudgetPaused
            from .online_research import approved
            try:
                page=self.app.documents.page(args['document_id'],args.get('page'))
                if not approved(page['source_url'],self.web.settings()['domains']):
                    return {'status':'failed','reason':'自动参数核对仅接受允许的原厂来源；Agent应继续寻找原厂证据，不要求用户填写审核表'}
                result=self.app.parameters.auto_review(args,self.model_settings().model())
                return {'status':'passed' if result['status']=='recorded' else 'failed','result':result,
                        'reason':result.get('reason'),'attempted_fields':{k:args.get(k) for k in ('document_id','page','model','parameter','value','unit','conditions','quote_id')},
                        'repair_instruction':'字段或工况不匹配时先按现有原文修正字段，不重复搜索；不能扩大为实机或整机能力。'}
            except BudgetPaused:raise
            except ValueError as exc:return {'status':'failed','reason':str(exc)[:500],'human_research_required':False,
                **({'failure_code':exc.code,'field':exc.field} if hasattr(exc,'code') else {}),
                'attempted_fields':{k:args.get(k) for k in ('document_id','page','model','parameter','value','unit','conditions','quote_id')},
                'repair_instruction':'先修正所列提交字段，已有原文无需重新搜索。'}
        self.app.tools.register('parameters.auto_review',auto_parameter,lambda args:None)
        def auto_fact(args):
            from .local_model import LocalSettings,BudgetPaused
            from .online_research import approved
            try:
                page=self.app.documents.page(args['document_id'],args.get('page'))
                if not approved(page['source_url'],self.web.settings()['domains']):raise ValueError('关系核对需要允许的原厂来源')
                result=self.app.parameters.auto_fact(args,self.model_settings().model())
                return {'status':'passed' if result['status']=='recorded' else 'failed','result':result,'reason':result.get('reason')}
            except BudgetPaused:raise
            except ValueError as exc:return {'status':'failed','reason':str(exc)[:500],'human_research_required':False,
                **({'failure_code':exc.code,'field':exc.field} if hasattr(exc,'code') else {})}
        self.app.tools.register('facts.auto_review',auto_fact,lambda args:None)
        from .research_report import evaluate as research_report
        self.app.tools.register('research.conclude',lambda args:{'status':'passed','report':research_report(args,self.app.parameters.facts())},lambda args:None)
        def fetch_result(args):
            result=self.web.import_url(args['project_id'],args['url'])
            return {'status':'passed' if result['status']=='imported' else 'unsupported' if result['status']=='not_configured' else 'failed','import_result':result}
        self.app.tools.register('documents.fetch',fetch_result,lambda args:None)
        self.app.tools.register('keil.source', lambda args: {'status': 'passed', 'source': keil.read_source(self.root, self.get(args['project_id'])['artifacts']['keil_project'], args['file'])}, lambda args: None)
        self.app.tools.register('hardware.discover', lambda args: dict(hardware.discover(self.root), usb=hardware.usb_inventory()), lambda args: None)

    def model_settings(self):
        from .local_model import LocalSettings
        return self.settings_factory(self.root) if self.settings_factory else LocalSettings(self.root)

    def view(self, project):
        check=project.artifacts.get('draft_verification',{})
        firmware=project.artifacts.get('engineering_draft',{}).get('firmware',{}).get('files',{})
        current=bool(firmware and check.get('source_sha256')==draft_verification.source_hash(firmware))
        module=project.artifacts.get('mcu_implementation',{}).get('files',{})
        module_check=project.artifacts.get('mcu_behavior_tests',{})
        module_current=bool(module and module_check.get('source_sha256')==draft_verification.source_hash(module))
        return dict(project.to_dict(), stage=project.stage, mode='analyst_assisted',
                    verification={'firmware_build': project.artifacts.get('firmware_build', {}).get('status', 'not_run'), 'hardware': 'not_run',
                                  'keil_build': project.artifacts.get('keil_build', {}).get('status', 'not_run'),
                                  'host_tests': module_check.get('status','not_run') if module_current else check.get('host_tests',{}).get('status','not_run') if current else project.artifacts.get('verification', {}).get('status', 'not_run'),
                                  'mcu_object_compilation': check.get('mcu_compile',{}).get('status','not_run') if current else project.artifacts.get('mcu_build', {}).get('status', 'not_run')})

    def get(self, project_id):
        return self.view(self.app.store.load(project_id))

    def create(self, description):
        project = self.app.store.create(description)
        project.status = 'awaiting_analysis'
        project.events.append({'action': 'created', 'mode': 'analyst_assisted'})
        self.app.store.save(project)
        return self.view(project)

    def update(self, project_id, revision, operation, payload):
        if self.online_allowed_operations is not None and operation not in self.online_allowed_operations:
            raise ValueError('在线工作台未连接隔离编译执行器；此操作需要本机工具或专用执行环境，未执行')
        project = self.app.store.load(project_id)
        if type(revision) is not int or project.revision != revision:
            raise ValueError('项目版本已改变，请刷新后操作')
        if operation == 'product_documents':
            from .product_documents import generate, fingerprint
            from .local_model import LocalSettings
            if not project.artifacts.get('selected_plan'):raise ValueError('需先保存选定方案，再生成详细设计与清单')
            previous=project.artifacts.get('product_documents')
            if previous and previous.get('source_sha256')==fingerprint(project):
                if project.status!='documents_delivered' or hashlib.sha256(self.archive(project)).hexdigest()==project.artifacts['delivery']['sha256']:return self.view(project)
                document=previous  # Refresh packaging after a renderer update without a model call.
            else:
                model=self.model_settings().model()
                if model is None:raise ValueError('需启用模型，由Agent编写详细设计与元件清单')
                document=generate(self,project,model)
            if self.app.store.load(project_id).revision!=revision:raise ValueError('生成期间工程已变化，未覆盖新版本；本次模型调用仍计费')
            project.artifacts['product_documents']=document
            if project.status=='documents_delivered':
                archive=self.archive(project)
                project.artifacts['delivery']=dict(project.artifacts['delivery'],sha256=hashlib.sha256(archive).hexdigest(),size_bytes=len(archive))
        elif operation == 'draft_tests':
            if payload.get('confirmed') is not True or not project.artifacts.get('engineering_draft',{}).get('firmware'):
                raise ValueError('需要用户确认关联已有扩展测试，且工程源码已保存')
            suite=test_suites.load_audit(self.root,project.id,payload.get('suite_id'))
            suite['original_tests_sha256']=draft_regression.tests_hash(project.artifacts['engineering_draft']['firmware']['files'])
            previous=project.artifacts.get('draft_test_suite')
            if previous and previous['sha256']!=suite['sha256']:
                raise ValueError('已冻结扩展测试；不能通过替换用例绕过失败，请另行审核测试变更')
            project.artifacts['draft_test_suite']=suite
            project.artifacts.pop('draft_verification',None)
            project.artifacts.pop('draft_checkpoint',None)
            if project.artifacts.get('delivery'):
                project.events.append({'action':'draft_delivery_superseded','delivery':project.artifacts.pop('delivery')})
            project.status='draft_ready';project.stage_index=4
        elif operation == 'start_draft':
            if payload.get('confirmed') is not True or not project.artifacts.get('preliminary_acceptance'):
                raise ValueError('需要用户确认已接受待验证项的初步方案')
            if project.status not in ('documents_delivered','preliminary_design','draft_in_progress','draft_ready','draft_verified','draft_verification_failed'):
                raise ValueError('当前状态不能继续工程草案')
            if project.artifacts.get('delivery'):
                project.events.append({'action':'draft_delivery_superseded','delivery':project.artifacts.pop('delivery')})
            project.status='draft_ready' if project.artifacts.get('engineering_draft',{}).get('firmware') else 'draft_in_progress'
            project.stage_index=3
        elif operation == 'draft_verify':
            if project.status not in ('draft_ready','draft_verification_failed'):
                raise ValueError('需要完整图纸和源码草案后才能验证')
            files=project.artifacts['engineering_draft']['firmware']['files']
            suite=project.artifacts.get('draft_test_suite')
            if suite and suite.get('original_tests_sha256')!=draft_regression.tests_hash(files):
                raise ValueError('已冻结原测试发生变化，拒绝验证；需要用户审核测试变更')
            project.artifacts['draft_validation_cpu']=payload.get('cpu')
            report=test_suites.verify_all(self.root,files,payload.get('cpu'),project.artifacts.get('draft_test_suite'))
            rolled_back=draft_regression.preserve(project.artifacts,report)
            project.artifacts['draft_last_check']=report
            if not rolled_back: project.artifacts['draft_verification']=report
            project.status='draft_verified' if project.artifacts['draft_verification']['status']=='passed' else 'draft_verification_failed'
        elif operation in ('draft_edit','draft_patch'):
            if project.status not in ('draft_ready','draft_verification_failed','draft_verified'): raise ValueError('当前无可修改的完整草案')
            from copy import deepcopy
            firmware=project.artifacts['engineering_draft']['firmware']
            files=deepcopy(firmware['files']);changes=payload.get('changes')
            if operation=='draft_patch':
                name=payload.get('file')
                if name not in files or not name.endswith(('.c','.h')) or name.startswith('test_'): raise ValueError('仅替换已有应用源码，不改测试')
                if payload.get('sha256')!=hashlib.sha256(files[name].encode()).hexdigest(): raise ValueError('源码哈希过期')
                replacements=payload.get('replacements')
                if not isinstance(replacements,list) or not 1<=len(replacements)<=6: raise ValueError('每次1至6处唯一文本替换')
                body=files[name]
                for replacement in replacements:
                    old,new=replacement.get('old'),replacement.get('new')
                    if not isinstance(old,str) or not old or not isinstance(new,str) or old==new or body.count(old)!=1:
                        raise ValueError('old必须唯一匹配当前源码且new确有变化，不能含省略号占位')
                    body=body.replace(old,new,1)
                changes=[{'file':name,'sha256':payload['sha256'],'content':body}]
            if not isinstance(changes,list) or not 1<=len(changes)<=3: raise ValueError('每次修改1至3个文件')
            for change in changes:
                name=change.get('file');body=change.get('content')
                if name not in files or not name.endswith(('.c','.h')) or name.startswith('test_'): raise ValueError('仅修改已有应用源码，保留原测试')
                if change.get('sha256')!=hashlib.sha256(files[name].encode()).hexdigest(): raise ValueError('源码哈希过期，请按当前文件修正')
                if not isinstance(body,str) or not body.strip(): raise ValueError('源码不能为空')
                files[name]=body
            updated=draft.save(project.artifacts['engineering_draft'],{'stage':'firmware','files':files,'rationale':payload.get('rationale'),
                         'assumptions':firmware['assumptions'],'open_items':firmware['open_items']})
            draft_regression.checkpoint(project.artifacts)
            project.events.append({'action':'engineering_draft_superseded','artifacts':project.artifacts['engineering_draft']})
            project.artifacts['engineering_draft']=updated;project.artifacts.pop('draft_verification',None)
            project.status='draft_ready'
        elif operation == 'draft_artifacts':
            if project.status not in ('draft_in_progress','draft_ready','draft_verification_failed','draft_verified'): raise ValueError('请先由用户开启工程草案')
            if (project.status=='draft_verification_failed' or project.artifacts.get('draft_test_suite')) and payload.get('stage')=='firmware':
                old_files=project.artifacts['engineering_draft']['firmware']['files']
                for name,body in old_files.items():
                    if name.startswith('test_') and name.endswith('.c') and payload.get('files',{}).get(name)!=body:
                        raise ValueError('修复必须保留原失败测试，不得删除或改写断言来绕过失败；测试需变更时由用户核对')
            saved_draft=draft.save(project.artifacts.get('engineering_draft'),payload)
            draft_regression.checkpoint(project.artifacts)
            project.artifacts.pop('draft_verification',None)
            if project.artifacts.get('engineering_draft'):
                project.events.append({'action':'engineering_draft_superseded','artifacts':project.artifacts['engineering_draft']})
            project.artifacts['engineering_draft']=saved_draft
            project.status='draft_ready' if project.artifacts['engineering_draft'].get('firmware') else 'draft_in_progress'
            project.stage_index=4 if project.status=='draft_ready' else 3
        elif operation in ('hardware_bind', 'hardware_capture'):
            if operation == 'hardware_bind':
                binding = hardware.bind(self.root, payload)
                if 'hardware_binding' in project.artifacts: project.events.append({'action': 'hardware_binding_superseded', 'binding': project.artifacts['hardware_binding']})
                project.artifacts['hardware_binding'] = binding
            else:
                binding = project.artifacts.get('hardware_binding')
                if not binding: raise ValueError('需要用户先选择并授权串口')
                captures = project.artifacts.setdefault('hardware_captures', [])
                if len(captures) >= 20: raise ValueError('本项目已采集20次，请导出记录后另建验证项目')
                captures.append(hardware.capture(self.root, binding, payload.get('seconds', 3)))
            if project.artifacts.get('delivery'):
                project.events.append({'action': 'delivery_superseded', 'delivery': project.artifacts.pop('delivery')})
                if project.status == 'documents_delivered': project.status = 'ready_delivery'
        elif operation == 'keil_import':
            if payload.get('confirmed') is not True: raise ValueError('请明确确认导入可信本地工程并允许构建副本')
            imported = keil.import_project(self.root, project.id, payload.get('file'), payload.get('target'))
            if 'keil_project' in project.artifacts: project.events.append({'action': 'keil_project_superseded', 'project': project.artifacts['keil_project']})
            project.artifacts['keil_project'] = imported
            project.artifacts.pop('keil_build', None); project.artifacts.pop('delivery', None)
            project.status, project.stage_index = 'ready_keil_build', 4
        elif operation == 'keil_edit':
            if project.status not in ('keil_build_failed', 'ready_keil_build', 'ready_delivery','documents_delivered'): raise ValueError('当前状态不允许修改 Keil 副本')
            if 'keil_project' not in project.artifacts: raise ValueError('需要先导入 Keil 工程')
            edit = keil.edit_source(self.root, project.artifacts['keil_project'], payload.get('changes'), payload.get('rationale'))
            project.events.append({'action': 'keil_edit_applied', **edit})
            project.artifacts.pop('delivery', None)
            if 'keil_build' in project.artifacts: project.events.append({'action': 'keil_build_superseded', 'result': project.artifacts.pop('keil_build')})
            project.status = 'ready_keil_build'
        elif operation == 'keil_build':
            if project.status not in ('ready_keil_build', 'keil_build_failed'): raise ValueError('需要先导入工程或修改源码')
            if project.artifacts.get('keil_build', {}).get('uncertain'): raise ValueError('此前构建超时，请先核实进程状态，再由用户重新导入工程')
            result = keil.build(self.root, project.artifacts['keil_project'])
            project.artifacts['keil_build'] = result
            project.status = 'ready_delivery' if result['status'] == 'passed' else 'keil_build_failed'
        elif operation == 'power_estimate':
            if project.artifacts.get('requirements',{}).get('status')!='confirmed': raise ValueError('先确认需求再进行整机估算')
            model=payload.get('model'); report=evaluate_power(model)
            references=[]
            for state in model['states']:
                citations=state.get('sources',[])
                if not isinstance(citations,list) or len(citations)>12: raise ValueError('估算来源格式不正确')
                if state['source_type']=='datasheet_estimate' and not citations: raise ValueError('手册估算需引用原文；无来源请标为assumption')
                for citation in citations:
                    if not isinstance(citation,dict) or not text(citation.get('quote')): raise ValueError('来源需包含原文')
                    page=self.app.documents.page(citation.get('document_id'),citation.get('page'))
                    quote=' '.join(citation['quote'].split())
                    if len(quote)<8 or quote not in ' '.join(page['text'].split()): raise ValueError('估算引用不在指定页面')
                    references.append({'state':state['name'],'document_id':page['document_id'],'page':page['page'],'citation':page['citation'],'sha256':page['sha256'],'quote':citation['quote'],'reviewed':False})
            report['source_references']=references
            loop=project.artifacts.get('design_loop'); candidate_id=payload.get('candidate_id')
            if loop and any(o['kind']=='energy' and o['fixed_inputs'].get('hours')!=model['target_hours'] for o in loop['rounds'][-1]['plan']['objectives']):
                raise ValueError('功耗估算的目标时长不能改变已冻结的续航需求')
            candidate=next((c for c in loop['rounds'][-1]['plan']['candidates'] if c['id']==candidate_id),None) if loop else project.artifacts.get('selected_plan')
            if not candidate or candidate['id']!=candidate_id: raise ValueError('请选择当前方案候选')
            estimates=project.artifacts.setdefault('power_estimates',{})
            if candidate_id in estimates: project.events.append({'action':'power_estimate_superseded','estimate':estimates[candidate_id]})
            estimates[candidate_id]={'candidate_id':candidate_id,'candidate_sha256':design.fingerprint(candidate),
                'requirements_sha256':design.fingerprint(project.artifacts['requirements']),'model':model,'report':report}
            if project.artifacts.pop('preliminary_acceptance',None): project.status='design_needs_evidence' if loop else 'selection_needs_evidence'
            obsolete={k:project.artifacts.pop(k) for k in ('delivery','implementation','build','verification','mcu_implementation','mcu_build','firmware_implementation','firmware_build') if k in project.artifacts}
            if obsolete: project.events.append({'action':'estimate_invalidated_downstream','artifacts':obsolete})
            if project.status=='documents_delivered': project.status='design_needs_evidence' if loop else 'selection_needs_evidence'
        elif operation == 'proceed_estimated_design':
            if payload.get('confirmed') is not True or payload.get('accept_open_items') is not True: raise ValueError('需明确接受未核价、估算和待实测事项')
            require_note=payload.get('rationale')
            if not text(require_note): raise ValueError('请说明为何在保留未解决事项下继续初步设计')
            loop=project.artifacts.get('design_loop'); cid=payload.get('candidate_id')
            candidate=next((c for c in loop['rounds'][-1]['plan']['candidates'] if c['id']==cid),None) if loop else project.artifacts.get('selected_plan')
            saved=project.artifacts.get('power_estimates',{}).get(cid)
            if not candidate or candidate['id']!=cid or not saved: raise ValueError('需要当前候选的功耗估算')
            if saved['candidate_sha256']!=design.fingerprint(candidate) or saved['requirements_sha256']!=design.fingerprint(project.artifacts['requirements']): raise ValueError('方案或需求已变化，请重新估算')
            for reference in saved['report'].get('source_references',[]):
                if self.app.documents.page(reference['document_id'],reference['page'])['sha256']!=reference['sha256']: raise ValueError('估算引用版本变化，请重新核对')
            report=evaluate_power(saved['model'])
            if report['status']=='insufficient_data': raise ValueError('关键估值不完整，先补充明确假设')
            project.artifacts['preliminary_acceptance']={'candidate_id':cid,'rationale':require_note,'estimate_sha256':report['model_sha256'],
                'power_status':report['status'],'peak_status':report['peak']['status'],'budget_status':'deferred_pending_quotes',
                'hardware':'not_run','scope':'preliminary_design_only','open_items':['采购价格与运费待核实','整机功耗与续航待实测','峰值、引脚、机构和功能仍需验证']}
            if report['status']=='estimated_shortfall': project.artifacts['preliminary_acceptance']['open_items'].append('保守估算续航不足目标，需优化负载或电池方案')
            if report['peak']['status']=='estimated_shortfall': project.artifacts['preliminary_acceptance']['open_items'].append('峰值电流估算存在供电缺口，需调整供电方案')
            project.artifacts['selected_plan']=dict(candidate,conditions=['初步设计选择，估算不是实测；预算待核价'],evidence_ids=[],chip_requirements=[],chip_options=[])
            project.status,project.stage_index='preliminary_design',3
        elif operation == 'design_plan':
            loop=design.plan(project,payload)
            obsolete={k:project.artifacts.pop(k) for k in ('engineering_draft','power_estimates','preliminary_acceptance','selected_plan','selection_proposal','selection_check','delivery','implementation','build','verification','mcu_implementation','mcu_build','firmware_implementation','firmware_build') if k in project.artifacts}
            if obsolete: project.events.append({'action':'design_invalidated_downstream','artifacts':obsolete})
            project.artifacts['design_loop']=loop
            project.status,project.stage_index='design_researching',1
        elif operation == 'design_research':
            project.artifacts['design_loop']=design.research(project,payload,self.app.documents,researcher=lambda query:self.web.autonomous_research(project.id,query))
            project.status='design_researching'
        elif operation == 'design_evaluate':
            loop=design.evaluate(project,self.app.parameters.get)
            project.artifacts['design_loop']=loop
            project.status={'constraints_feasible':'design_has_feasible','needs_evidence':'design_needs_evidence','no_feasible_option':'design_no_feasible'}[loop['rounds'][-1]['status']]
            project.stage_index=2
        elif operation == 'design_recommend':
            project.artifacts['design_loop']=design.recommend(project,payload)
        elif operation == 'design_accept':
            candidate,report=design.accept(project,payload,self.app.parameters.get)
            convert=lambda c:dict(c,conditions=['仅声明的约束完成检查，实机未验证'],evidence_ids=[],chip_requirements=[],chip_options=[])
            project.artifacts['selected_plan']=convert(candidate)
            if project.artifacts.get('comparison'): project.events.append({'action':'comparison_superseded','comparison':project.artifacts['comparison']})
            project.artifacts['comparison']={'candidates':[convert(c) for c in project.artifacts['design_loop']['rounds'][-1]['plan']['candidates']],
                'recommendation':{'candidate_id':candidate['id'],'reason':'用户确认本轮通过声明约束检查的方案'},'status':'constraints_checked','chip_selection':'hardware_not_verified'}
            project.artifacts['selection_proposal']=candidate['proposal']
            project.artifacts['selection_check']=report
            project.status,project.stage_index='selection_checked',2
        elif operation == 'implementation_scope':
            if payload.get('confirmed') is not True or payload.get('mode')!='mcu_compile':
                raise ValueError('需要用户明确确认切换为C语言MCU模块编译范围')
            if not project.artifacts.get('selected_plan'):raise ValueError('请先选择方案')
            previous={k:project.artifacts.pop(k) for k in ('implementation','build','verification','delivery','mcu_implementation','mcu_build') if k in project.artifacts}
            project.events.append({'action':'implementation_scope_changed','previous':previous,'decision':dict(project.artifacts['decision'])})
            project.artifacts['decision']=dict(project.artifacts['decision'],actions=['mcu_compile','export_documents'],rationale='用户要求C语言嵌入式实现；先验证MCU模块编译和主机行为，不等同完整板级固件或硬件验收')
            project.status,project.stage_index='awaiting_mcu_implementation',3
        elif operation == 'supplement':
            if not text(payload.get('message')):
                raise ValueError('补充内容不能为空')
            project.events.append({'action': 'invalidated', 'artifacts': project.artifacts})
            project.artifacts = {}
            project.description += '\n用户补充：' + payload['message'].strip()
            project.status, project.stage_index = 'awaiting_analysis', 0
        elif operation == 'analysis':
            if project.status not in ('awaiting_analysis', 'needs_input'):
                raise ValueError('当前状态不允许提交分析')
            requirements = validate_requirements(payload.get('requirements'))
            from .analysis import validate_budget_scope
            validate_budget_scope(requirements,project.description)
            evidence = {}
            for query in ['需求'] + requirements['search_queries']:
                for card in self.app.knowledge.search(query)[:3]:
                    evidence[card['id']] = card
            comparison = validate_comparison(payload.get('comparison'), requirements, list(evidence.values()))
            from .analysis_quality import validate as validate_analysis_quality
            quality = validate_analysis_quality(project.description, requirements, comparison)
            decision = payload.get('decision')
            if not isinstance(decision, dict) or not text(decision.get('rationale')) or not strings(decision.get('limitations'), True):
                raise ValueError('需要判断依据和能力限制')
            # Only actual implemented action is available in this version.
            if decision.get('actions') not in (['export_documents'], ['host_prototype', 'export_documents'], ['mcu_compile', 'export_documents'], ['firmware_build', 'export_documents']):
                raise ValueError('动作不在当前服务能力范围')
            if not text(payload.get('analyst')):
                raise ValueError('需要记录分析来源')
            project.artifacts = {'requirements': requirements, 'comparison': comparison,
                                 'analysis_quality': quality,
                                 'evidence': list(evidence.values()), 'decision': decision,
                                 'analyst': payload['analyst']}
            project.status = 'needs_input'
        elif operation == 'confirm':
            if project.status != 'needs_input':
                raise ValueError('需要先生成需求与方案草稿')
            # Recheck older saved analyses too; a legacy artifact must not bypass
            # a newly added guard merely because it was saved before the change.
            from .analysis_quality import validate as validate_analysis_quality
            quality = validate_analysis_quality(project.description, project.artifacts['requirements'], project.artifacts['comparison'])
            if any(q['blocking'] for q in project.artifacts['requirements']['questions']):
                raise ValueError('存在阻塞问题，请补充需求并重新分析')
            if payload.get('confirmed') is not True:
                raise ValueError('需要明确确认需求')
            project.artifacts['requirements']['status'] = 'confirmed'
            project.artifacts['analysis_quality'] = quality
            project.status, project.stage_index = 'awaiting_selection', 1
        elif operation == 'select':
            if project.status != 'awaiting_selection':
                raise ValueError('先确认需求再选择方案')
            candidates = project.artifacts['comparison']['candidates']
            selected = next((c for c in candidates if c['id'] == payload.get('candidate_id')), None)
            if selected is None:
                raise ValueError('方案不存在')
            project.artifacts['selected_plan'] = selected
            project.status = ('awaiting_implementation' if 'host_prototype' in project.artifacts['decision']['actions'] else 'ready_delivery')
            if 'mcu_compile' in project.artifacts['decision']['actions']:
                project.status = 'awaiting_mcu_implementation'
            if 'firmware_build' in project.artifacts['decision']['actions']:
                project.status = 'awaiting_firmware_implementation'
        elif operation == 'selection_check':
            loop=project.artifacts.get('design_loop')
            if loop and loop['rounds'][-1]['status']!='accepted': raise ValueError('方案推演未确认，请检查并选择本轮候选')
            if 'selected_plan' not in project.artifacts:
                raise ValueError('需要先选择方案')
            report = evaluate_selection(payload.get('proposal'), resolver=self.app.parameters.get)
            project.artifacts['selection_proposal'] = payload['proposal']
            project.artifacts['selection_check'] = report
            if project.artifacts.get('delivery'):
                project.events.append({'action': 'delivery_superseded', 'delivery': project.artifacts.pop('delivery')})
            project.stage_index = 2
            project.status = {'passed':'selection_checked', 'failed':'selection_failed', 'needs_evidence':'selection_needs_evidence'}[report['status']]
        elif operation == 'continue_selection':
            if project.status!='selection_checked' or payload.get('confirmed') is not True:
                raise ValueError('需要选型检查通过并明确确认继续')
            report=evaluate_selection(project.artifacts['selection_proposal'],resolver=self.app.parameters.get)
            if report['status']!='passed': raise ValueError('选型证据已失效，请重新检查')
            actions=project.artifacts['decision']['actions']
            project.status='awaiting_firmware_implementation' if 'firmware_build' in actions else 'awaiting_mcu_implementation' if 'mcu_compile' in actions else 'awaiting_implementation' if 'host_prototype' in actions else 'ready_delivery'
            project.stage_index=3
        elif operation == 'firmware_implementation':
            if project.status not in ('awaiting_firmware_implementation', 'firmware_build_failed'):
                raise ValueError('当前阶段不允许完整固件源码提交')
            validate_profile(payload.get('profile'))
            validate_sources(payload.get('files'), payload['profile']['cpu'])
            if not text(payload.get('rationale')):
                raise ValueError('需要实现依据')
            if 'firmware_implementation' in project.artifacts:
                project.events.append({'action': 'firmware_superseded', 'implementation': project.artifacts['firmware_implementation'], 'build': project.artifacts.get('firmware_build')})
            project.artifacts.pop('firmware_build', None)
            project.artifacts['firmware_implementation'] = {'files': payload['files'], 'profile': payload['profile'], 'rationale': payload['rationale']}
            project.status, project.stage_index = 'ready_firmware_build', 4
        elif operation == 'firmware_build':
            if project.status != 'ready_firmware_build':
                raise ValueError('需要先提交固件源码与内存配置')
            result = build_firmware(self.root, project)
            project.artifacts['firmware_build'] = result
            project.status = 'ready_delivery' if result['status'] == 'passed' else 'firmware_build_failed'
        elif operation == 'mcu_test':
            impl=project.artifacts.get('mcu_implementation')
            if not impl:raise ValueError('需要先保存MCU模块源码')
            files=impl['files'];entries=sorted(n for n in files if n.startswith('test_') and n.endswith('.c'))
            if not entries:raise ValueError('没有可运行的test_*.c测试入口')
            results={}
            for entry in entries:
                isolated={n:b for n,b in files.items() if n!='main.c' and (not n.startswith('test_') or n==entry)}
                results[entry]=draft_verification.verify(self.root,isolated,impl['cpu'])
            project.artifacts['mcu_behavior_tests']={'status':'passed' if all(r['status']=='passed' for r in results.values()) else 'failed',
                'source_sha256':draft_verification.source_hash(files),'entries':results,'hardware':'not_run','scope':'C_host_assertions_and_object_compile_not_complete_firmware'}
            project.artifacts.pop('delivery',None)
            project.status='ready_delivery' if project.artifacts['mcu_behavior_tests']['status']=='passed' and project.artifacts.get('mcu_build',{}).get('status')=='passed' else 'mcu_build_failed'
        elif operation == 'mcu_implementation':
            if project.status not in ('awaiting_mcu_implementation', 'mcu_build_failed'):
                raise ValueError('当前阶段不允许MCU源码提交')
            validate_sources(payload.get('files'), payload.get('cpu'))
            if not text(payload.get('rationale')):
                raise ValueError('需要实现或修改依据')
            if 'mcu_implementation' in project.artifacts:
                project.events.append({'action': 'mcu_superseded', 'implementation': project.artifacts['mcu_implementation'],
                                       'build': project.artifacts.get('mcu_build')})
            project.artifacts.pop('mcu_build', None)
            project.artifacts.pop('mcu_behavior_tests',None)
            project.artifacts['mcu_implementation'] = {'files': payload['files'], 'cpu': payload['cpu'], 'rationale': payload['rationale']}
            project.status, project.stage_index = 'ready_mcu_build', 4
        elif operation == 'mcu_build':
            if project.status != 'ready_mcu_build':
                raise ValueError('需要先提交MCU源码与目标配置')
            result = compile_project(self.root, project)
            project.artifacts['mcu_build'] = result
            project.status = 'ready_delivery' if result['status'] == 'passed' else 'mcu_build_failed'
        elif operation == 'implementation':
            if project.status not in ('awaiting_implementation', 'build_failed', 'test_failed'):
                raise ValueError('当前状态不允许代码提交')
            validate_files(payload.get('files'))
            if not text(payload.get('rationale')):
                raise ValueError('代码提交需要实现或修复依据')
            prior = {k: project.artifacts[k] for k in ('implementation', 'build', 'verification') if k in project.artifacts}
            if prior:
                project.events.append({'action': 'implementation_superseded', 'artifacts': prior})
            for key in ('build', 'verification', 'delivery'):
                project.artifacts.pop(key, None)
            project.artifacts['implementation'] = {'files': payload['files'], 'rationale': payload['rationale'], 'mode': 'host_behavioral_prototype'}
            project.status, project.stage_index = 'ready_build', 4
        elif operation == 'build':
            if project.status != 'ready_build':
                raise ValueError('需要先提交代码')
            result = run_host(self.root, project)
            project.artifacts['build'] = result
            project.status = 'ready_test' if result['status'] == 'passed' else 'build_failed'
        elif operation == 'test':
            if project.status != 'ready_test':
                raise ValueError('需要通过主机编译')
            result = run_host(self.root, project, testing=True)
            project.artifacts['verification'] = result
            project.status = 'ready_delivery' if result['status'] == 'passed' else 'test_failed'
            project.stage_index = 6 if result['status'] == 'passed' else 5
        elif operation == 'execute':
            if project.status not in ('ready_delivery','preliminary_design','draft_verified'):
                raise ValueError('需求确认及方案选择未完成')
            if project.artifacts.get('engineering_draft'):
                check=project.artifacts.get('draft_verification',{})
                files=project.artifacts['engineering_draft']['firmware']['files']
                if not test_suites.current(check,files,project.artifacts.get('draft_test_suite')):
                    raise ValueError('工程草案需通过当前源码及冻结测试集的真实编译、原测试和扩展测试，不能复用旧报告')
            # A real tool is executed; hardware stages remain unexecuted.
            history=self.web.history(project.id)
            if history['searches'] or history['documents']:
                project.artifacts['online_research_snapshot']=history
            project.artifacts['delivery_assessment'] = assess(self.view(project))
            archive = self.archive(project)
            project.artifacts['delivery'] = {'kind': 'engineering_draft' if 'engineering_draft' in project.artifacts else 'demonstration_firmware' if 'firmware_build' in project.artifacts else 'documentation', 'sha256': hashlib.sha256(archive).hexdigest(),
                                              'size_bytes': len(archive), 'firmware_build': project.artifacts.get('firmware_build', {}).get('status', 'not_run'), 'hardware': 'not_run'}
            project.status, project.stage_index = 'documents_delivered', 7
        else:
            raise ValueError('操作不存在')
        project.events.append({'action': operation, 'source_revision': revision})
        project.revision += 1
        self.app.store.save(project)
        return self.view(project)

    def archive(self, project):
        artifacts = project.artifacts
        research_history=artifacts.get('online_research_snapshot')
        content = {
            'README.md': '# 嵌入式项目文档交付\n\n此包是分析与设计文档，不含已验证固件。\n固件构建、器件电气验证和实机测试尚未执行。\n\n需求：\n' + project.description,
            'requirements.json': json.dumps(artifacts.get('requirements'), ensure_ascii=False, indent=2),
            'analysis-quality.json': json.dumps(artifacts.get('analysis_quality', {'status':'not_run','scope':'legacy_analysis_not_checked'}), ensure_ascii=False, indent=2),
            'candidate-plans.json': json.dumps(artifacts.get('comparison'), ensure_ascii=False, indent=2),
            'selected-plan.json': json.dumps(artifacts.get('selected_plan'), ensure_ascii=False, indent=2),
            'decision.json': json.dumps(artifacts.get('decision'), ensure_ascii=False, indent=2),
            'evidence.json': json.dumps(artifacts.get('evidence'), ensure_ascii=False, indent=2),
            'verification-plan.md': '# 验证计划\n\n逐项执行 requirements.json 中的验收标准，记录预期、实际、环境和版本。\n当前状态：未执行。具体量化测试参数需在工程实现前补齐。\n',
        }
        if 'delivery_assessment' in artifacts:
            content['delivery-assessment.json'] = json.dumps(artifacts['delivery_assessment'], ensure_ascii=False, indent=2)
        if 'hardware_binding' in artifacts:
            content['hardware-binding.json'] = json.dumps(artifacts['hardware_binding'], ensure_ascii=False, indent=2)
            content['hardware-captures.json'] = json.dumps(artifacts.get('hardware_captures', []), ensure_ascii=False, indent=2)
            for capture in artifacts.get('hardware_captures', []):
                raw = base64.b64decode(capture['raw_base64'], validate=True)
                if hashlib.sha256(raw).hexdigest() != capture['sha256']: raise ValueError('硬件日志原始字节校验失败')
                content['hardware-logs/' + capture['id'] + '.bin'] = raw
        if 'keil_project' in artifacts:
            folder, _ = keil.workspace(self.root, artifacts['keil_project'])
            files = [p for p in folder.rglob('*') if p.is_file()]
            if len(files) > 5000 or sum(p.stat().st_size for p in files) > 150_000_000: raise ValueError('Keil 交付副本过大')
            for file in files:
                checked = keil.inside(folder, file.relative_to(folder).as_posix())
                content['keil-project/' + file.relative_to(folder).as_posix()] = checked.read_bytes()
            content['keil-build-result.json'] = json.dumps(artifacts.get('keil_build'), ensure_ascii=False, indent=2)
            content['keil-edit-history.json'] = json.dumps([e for e in project.events if e.get('action') in ('keil_edit_applied', 'keil_build_superseded')], ensure_ascii=False, indent=2)
            content['README.md'] += '\n\n包含导入副本的 Keil 工程与真实构建日志。构建成功不代表已烧录或实机运行。\n'
        if 'implementation' in artifacts:
            content.update({'host-prototype/' + n: b for n, b in artifacts['implementation']['files'].items()})
            content['build-result.json'] = json.dumps(artifacts.get('build'), ensure_ascii=False, indent=2)
            content['host-test-result.json'] = json.dumps(artifacts.get('verification'), ensure_ascii=False, indent=2)
            content['debug-history.json'] = json.dumps([e for e in project.events if e.get('action') == 'implementation_superseded'], ensure_ascii=False, indent=2)
            content['README.md'] += '\n\n包含已在主机执行的行为原型与测试，非 MCU 固件。详见 build-result.json 和 host-test-result.json。\n'
        if 'selection_check' in artifacts:
            content['selection-check.json'] = json.dumps(artifacts['selection_check'], ensure_ascii=False, indent=2)
        if 'design_loop' in artifacts:
            content['design-reasoning-history.json']=json.dumps(artifacts['design_loop'],ensure_ascii=False,indent=2)
        if research_history and (research_history['searches'] or research_history['documents']):
            content['online-research.json']=json.dumps(research_history,ensure_ascii=False,indent=2)
        if 'draft_verification' in artifacts:
            content['draft-verification.json']=json.dumps(artifacts['draft_verification'],ensure_ascii=False,indent=2)
        if 'draft_test_suite' in artifacts:
            suite=artifacts['draft_test_suite']
            content['additional-verification/suite.json']=json.dumps(suite,ensure_ascii=False,indent=2)
            for name,body in test_suites.validate(suite).items():
                content['additional-verification/tests/'+name+'.c']=body
        if 'engineering_draft' in artifacts:
            content['engineering-draft-manifest.json']=json.dumps(artifacts['engineering_draft'],ensure_ascii=False,indent=2)
            for stage in draft.STAGES:
                for name,body in artifacts['engineering_draft'].get(stage,{}).get('files',{}).items():
                    content['engineering-draft/'+stage+'/'+name]=body
        if 'power_estimates' in artifacts:
            content['power-estimates.json']=json.dumps(artifacts['power_estimates'],ensure_ascii=False,indent=2)
        if 'preliminary_acceptance' in artifacts:
            content['preliminary-design-scope.json']=json.dumps(artifacts['preliminary_acceptance'],ensure_ascii=False,indent=2)
            content['README.md']='# 初步设计文档（保留未解决事项）\n\n采购预算待核价；功耗、续航与峰值仅为估算，实机未测试。估算存在缺口时仍明确记录，不代表100元或48小时已达标。\n\n'+project.description
        if 'engineering_draft' in artifacts:
            check=artifacts.get('draft_verification',{})
            content['README.md']+='\n\n包含接口表、SVG连接草图和C源码草案。当前软件验证：'+check.get('status','not_run')+'；详细范围见 draft-verification.json。对象编译与mock测试不等于完整链接、电气审查或硬件验证。此SVG不是PCB生产图。\n'
        if 'mcu_implementation' in artifacts:
            content.update({'mcu-source/' + n: b for n, b in artifacts['mcu_implementation']['files'].items()})
            result = artifacts.get('mcu_build', {})
            metadata = dict(result, objects={n: {k: v for k, v in item.items() if k != 'base64'} for n, item in result.get('objects', {}).items()})
            content['mcu-build-result.json'] = json.dumps(metadata, ensure_ascii=False, indent=2)
            for name, item in result.get('objects', {}).items():
                raw = base64.b64decode(item['base64'], validate=True)
                if hashlib.sha256(raw).hexdigest() != item['sha256']:
                    raise ValueError('目标文件哈希不一致')
                content['mcu-objects/' + name] = raw
            content['README.md'] += '\n\n包含MCU目标文件编译记录；尚未链接成可烧录固件，未做运行验证。\n'
            entries=sorted(n for n in artifacts['mcu_implementation']['files'] if n.startswith('test_') and n.endswith('.c'))
            content['mcu-source/TESTING.md']='# C模块复测\n\n各test_*.c是独立入口，不能一起链接（会重复main）。每次只选择一个测试入口，配合非test_生产.c文件编译运行。\n\n测试入口：\n'+''.join('- '+n+'\n' for n in entries)+'\n主机断言不模拟真实GPIO、电源或传感器。MCU目标文件编译不等于完整固件链接、烧录或实机通过。\n'
            check=artifacts.get('mcu_behavior_tests',{})
            if check.get('source_sha256')==draft_verification.source_hash(artifacts['mcu_implementation']['files']):
                content['mcu-behavior-tests.json']=json.dumps(check,ensure_ascii=False,indent=2)
                content['README.md']+='\n当前C模块主机行为测试：'+check['status']+'；实际工具记录见mcu-behavior-tests.json。\n'
        if 'firmware_implementation' in artifacts:
            impl = artifacts['firmware_implementation']
            content.update({'firmware-source/' + n: b for n, b in impl['files'].items()})
            result = artifacts.get('firmware_build', {})
            content.update({'firmware-source/' + n: b for n, b in result.get('generated_sources', {}).items()})
            content['board-profile.json'] = json.dumps(impl['profile'], ensure_ascii=False, indent=2)
            metadata = {k: v for k, v in result.items() if k not in ('objects', 'images')}
            for group in ('images', 'objects'):
                metadata[group] = {n: {k: v for k, v in item.items() if k != 'base64'} for n, item in result.get(group, {}).items()}
            content['firmware-build-result.json'] = json.dumps(metadata, ensure_ascii=False, indent=2)
            for name, item in result.get('images', {}).items():
                raw = base64.b64decode(item['base64'], validate=True)
                if hashlib.sha256(raw).hexdigest() != item['sha256']:
                    raise ValueError('固件产物哈希不一致')
                content['firmware-images/' + name] = raw
            content['README.md'] = '# 固件构建演练交付\n\n包含真实工具链生成的AXF、BIN、HEX和Map。仅对应演练内存配置，不允许据此判断实际板卡可烧录。\n硬件时钟、GPIO、外部中断、外设和实机行为未验证。\n\n' + project.description
        buffer = io.BytesIO()
        document=artifacts.get('product_documents')
        if document:
            from .product_documents import exports, fingerprint
            if document.get('source_sha256')==fingerprint(project):
                content.update(exports(document))
                content['README.md']+='\n\n详细产品设计与制作说明见 product-design/产品详细设计与制作说明.html，可编辑正文为同目录 Markdown，元件清单为 UTF-8 CSV。所有未核价物料保持待核价。\n'
                if document.get('wiring_evidence'):
                    content['README.md']+='\n候选引脚以 engineering-draft/interfaces/PIN_ASSIGNMENT.md 和 pin-bindings.json 为接线证据补充；product-design/候选引脚映射.svg 为可缩放示意。旧接口文件中的TBD与通道占位不等于板级配置，逻辑PWM编号不能直接当作芯片TIM通道。\n'
            else:
                content['product-design/文档已过期.md']='# 设计文档需更新\n\n工程来源已经变化，旧设计与清单不再作为当前交付文档。请重新生成。\n'
        with ZipFile(buffer, 'w', ZIP_DEFLATED) as archive:
            for name, body in content.items():
                from zipfile import ZipInfo
                info = ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
                info.compress_type = ZIP_DEFLATED
                archive.writestr(info, body)
        return buffer.getvalue()

    def download(self, project_id):
        project = self.app.store.load(project_id)
        if project.status != 'documents_delivered':
            raise ValueError('文档尚未交付')
        archive = self.archive(project)
        if hashlib.sha256(archive).hexdigest() != project.artifacts['delivery']['sha256']:
            raise ValueError('交付内容校验失败')
        return archive
