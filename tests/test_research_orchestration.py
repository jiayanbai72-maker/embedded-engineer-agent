import unittest
from unittest.mock import MagicMock,patch
import test_control
from embedded_agent.autonomy import AutonomousRunner,ModelDecider
from embedded_agent.research_orchestration import recovery,progress,contract,instruction,validate_goal,completion,EvidenceError


class RecoveryPolicyTests(unittest.TestCase):
    def test_completion_requires_exact_valid_registry_target(self):
        goal={'model':'X','parameter':'minimum','value':1.8,'unit':'V'}
        context={'run':{'evidence_goal':goal},'registered_parameters':[dict(goal,id='PAR-1',valid=True)]}
        self.assertEqual(completion(context)['status'],'verified')
        for changes in ({'value':3.3},{'valid':False},{'unit':'mV'},{'parameter':'maximum'}):
            context['registered_parameters']=[dict(goal,id='PAR-1',valid=True,**{})|changes]
            self.assertEqual(completion(context)['status'],'ended_with_gaps')
        context['run'].pop('evidence_goal')
        self.assertEqual(completion(context)['status'],'ended_with_gaps')

    def test_typed_error_does_not_depend_on_message_language(self):
        from embedded_agent.adapters import ToolRegistry
        registry=ToolRegistry()
        def fail(args):raise EvidenceError('source_reference','localized arbitrary message','quote_id')
        registry.register('facts.auto_review',fail,lambda a:None)
        result=registry.execute('facts.auto_review',{'quote_id':'expired'})
        self.assertEqual(result['failure_code'],'source_reference')
        self.assertEqual(result['field'],'quote_id')

    def test_empty_receipt_payload_is_not_progress(self):
        self.assertEqual(progress({'observations':[{'status':'executed','tool_result':None}]})['verified_records'],0)

    def test_unreadable_layout_keeps_gap_without_read_loop(self):
        context=self.context('source_layout');plan=recovery(context)
        context['run']['source_recovery_attempts']={plan['recovery_key']:1}
        self.assertEqual(recovery(context)['phase'],'repair_claim_from_existing_source')
        self.assertIsNone(recovery(context)['automatic_action'])

    def test_network_failure_never_becomes_automatic_paid_replay(self):
        context=self.context('unknown')
        context['run']['auto_feedback'].update(action='fetch_document',attempted_fields={'url':'https://example.invalid/a.pdf'})
        self.assertIsNone(recovery(context)['automatic_action'])
    def context(self,code='source_reference'):
        return {'run':{'scope':'research_only','steps':1,'observations':[],
            'auto_feedback':{'status':'failed','failure_code':code,'action':'record_fact',
                'attempted_fields':{'document_id':'DOC-unseen-QZ241','page':7,'source_view':'text'}}},
            'limits':{'remaining_steps':5},'allowed_actions':['read_document_page','record_fact','finish']}

    def test_source_recovery_is_bounded_and_does_not_depend_on_part_name(self):
        context=self.context();plan=recovery(context)
        self.assertEqual(plan['automatic_action']['arguments']['document_id'],'DOC-unseen-QZ241')
        context['run']['source_recovery_attempts']={plan['recovery_key']:1}
        self.assertIsNone(recovery(context)['automatic_action'])

    def test_layout_recovery_uses_same_source_not_new_search(self):
        plan=recovery(self.context('source_layout'))
        self.assertEqual(plan['automatic_action'],{'action':'read_document_page','arguments':{'document_id':'DOC-unseen-QZ241','page':7,'source_view':'layout'}})

    def test_web_source_recovery_does_not_invent_pdf_page(self):
        context=self.context();context['run']['auto_feedback']['attempted_fields']['page']=None
        self.assertIsNone(recovery(context)['automatic_action']['arguments']['page'])
        context['run']['auto_feedback']['failure_code']='source_layout'
        self.assertIsNone(recovery(context)['automatic_action'])

    def test_budget_integrity_and_semantics_are_not_blindly_retried(self):
        for code in ('budget','source_integrity','semantic_evidence','argument_validation','output_schema'):
            self.assertIsNone(recovery(self.context(code))['automatic_action'],code)
        context=self.context();context['limits']['remaining_steps']=1
        self.assertEqual(recovery(context)['phase'],'conclude_with_current_evidence')

    def test_progress_requires_successful_receipts_not_model_claims(self):
        run={'steps':3,'observations':[{'status':'rejected','tool_result':{'result':{'status':'recorded','fact':{'id':'fake'}}}},
            {'status':'executed','tool_result':{'result':{'status':'recorded','fact':{'id':'real'}}}},
            {'status':'executed','tool_result':{'result':{'status':'recorded','fact':{'id':'real'}}}}]}
        self.assertEqual(progress(run)['verified_records'],1)

    def test_task_contract_and_prompts_do_not_embed_known_component_answer(self):
        self.assertIn('no_pwm_uart_pin_overlap',contract('pwm_review')['checks'])
        self.assertNotIn('STM32L031',instruction('pwm_review'))
        self.assertNotIn('PA5',instruction('pwm_review'))

    def test_goal_validation_cannot_smuggle_actions_or_nonfinite_values(self):
        self.assertEqual(validate_goal({'model':'NEW17','subject':'P9','predicate':'BANK2','object':'SIG3'})['model'],'NEW17')
        for invalid in ({'model':'X','subject':'P9'},{'model':'X','parameter':'v','value':float('nan'),'unit':'V'},{'model':'X','parameter':'v','value':True,'unit':'V'},{'model':'X','action':'shell'}):
            with self.assertRaises(ValueError):validate_goal(invalid)

    def test_goal_rejects_partial_mixed_types(self):
        relation={'model':'X','subject':'P1','predicate':'AF1','object':'SIG'}
        numeric={'model':'X','parameter':'v','value':1.8,'unit':'V'}
        for goal in (relation|{'unit':'V'},relation|{'value':1},numeric|{'predicate':'AF1'},numeric|{'object':'SIG'}):
            with self.assertRaises(ValueError):validate_goal(goal)

    def test_integrity_block_has_priority_over_last_step(self):
        context=self.context('source_integrity');context['limits']['remaining_steps']=1
        self.assertEqual(recovery(context)['phase'],'blocked_source_integrity')


class RecoveryRunnerTests(unittest.TestCase):
    setUp=test_control.ControlTests.setUp
    tearDown=test_control.ControlTests.tearDown
    prepared=test_control.ControlTests.prepared

    def test_normalization_failure_keeps_the_actual_response_for_repair(self):
        run=self.prepared();provider=MagicMock()
        provider.decide.return_value={'action':'invented_tool','arguments':{'field':'bad'},'reason':'fixture'}
        result=AutonomousRunner(self.control,provider).step(run['id'])
        feedback=result['context']['run']['auto_feedback']
        self.assertEqual(feedback['action'],'invented_tool')
        self.assertEqual(feedback['attempted_arguments'],{'field':'bad'})
        self.assertIn('有效动作',feedback['message'])

    def test_documentation_scope_rejects_implementation_and_exposes_analysis_limit(self):
        old=self.prepared();run=self.control.create(old['project_id'],scope='documentation_only')
        context=self.control.context(run['id'])
        self.assertNotIn('implementation',context['allowed_actions'])
        with self.assertRaises(ValueError):
            self.control.submit(run['id'],run['revision'],{'id':'D','project_revision':run['project_revision'],'action':'implementation','arguments':{},'rationale':'test','expected':'test','source':'fixture'})
        fresh=self.service.create('只做需求与方案文档')
        run=self.control.create(fresh['id'],scope='documentation_only')
        schema=self.control.context(run['id'])['action_contracts']['analysis']['arguments_schema']
        self.assertEqual(schema['properties']['decision']['properties']['actions']['enum'],[['export_documents']])

    def test_budget_scope_does_not_accept_invented_explicit_exclusions(self):
        from embedded_agent.analysis import validate_budget_scope
        row={'origin':'explicit','description':'整机材料预算80元，不含线材与运费'}
        with self.assertRaises(ValueError):validate_budget_scope({'requirements':[row]},'材料预算80元')
        validate_budget_scope({'requirements':[dict(row,origin='proposed')]},'材料预算80元')
        validate_budget_scope({'requirements':[row]},'整机材料预算80元，不含线材与运费')

    def test_service_preserves_typed_source_errors_for_both_registry_tools(self):
        self.prepared()
        for name in ('parameters.auto_review','facts.auto_review'):
            with patch.object(self.service.app.documents,'page',side_effect=EvidenceError('source_integrity','localized source changed','document_id')):
                result=self.service.app.tools.execute(name,{'document_id':'DOC-X','page':7})
            self.assertEqual(result['failure_code'],'source_integrity')
            self.assertEqual(result['field'],'document_id')

    def test_integrity_failure_does_not_call_model_or_tools(self):
        old=self.prepared();run=self.control.create(old['project_id'],scope='research_only')
        run['auto_feedback']={'status':'failed','failure_code':'source_integrity'};self.control.save(run)
        provider=MagicMock()
        with patch.object(self.service.app.tools,'execute') as execute:
            result=AutonomousRunner(self.control,provider).step(run['id'])
            execute.assert_not_called()
        provider.decide.assert_not_called();self.assertEqual(result['reason_code'],'source_integrity')

    def test_research_can_finish_before_delivery_without_changing_engineering_stage(self):
        old=self.prepared();run=self.control.create(old['project_id'],scope='research_only',max_steps=2)
        before=self.service.get(old['project_id'])
        self.assertNotIn('finish',self.control.context(run['id'])['allowed_actions'])
        run['observations']=[{'action':'read_document_page','status':'executed'}];run['steps']=1;self.control.save(run)
        self.assertEqual(self.control.context(run['id'])['allowed_actions'],['finish'])
        provider=MagicMock();provider.decide.return_value={'action':'finish','arguments':{},'reason':'source gap remains'}
        result=AutonomousRunner(self.control,provider).step(run['id'])
        self.assertEqual(result['status'],'complete')
        after=self.service.get(old['project_id'])
        self.assertEqual(after['status'],before['status']);self.assertEqual(after['revision'],before['revision'])
        self.assertEqual(result['context']['run']['evidence_completion']['status'],'ended_with_gaps')

    def test_new_source_progress_resets_stall_but_duplicate_page_does_not(self):
        old=self.prepared();run=self.control.create(old['project_id'],scope='research_only')
        run.update(repeat_recovery_count=1);self.control.save(run)
        provider=MagicMock()
        provider.decide.return_value={'action':'read_document_page','arguments':{'document_id':'DOC-X','page':3},'reason':'read'}
        page={'status':'passed','page':{'document_id':'DOC-X','page':3,'sha256':'hash'}}
        with patch.object(self.service.app.documents,'document',return_value={'sha256':'hash','text_sha256':'text'}), patch.object(self.service.app.tools,'execute',return_value=page):
            AutonomousRunner(self.control,provider).step(run['id'])
        saved=self.control.load(run['id']);self.assertEqual(saved['repeat_recovery_count'],0)
        # Controller restart preserves receipts; repeated work must not rerun the tool.
        from embedded_agent.control import DecisionController
        with patch.object(self.service.app.documents,'document',return_value={'sha256':'hash','text_sha256':'text'}), patch.object(self.service.app.tools,'execute') as execute:
            AutonomousRunner(DecisionController(self.service),provider).step(run['id'])
            execute.assert_not_called()
        self.assertEqual(self.control.load(run['id'])['repeat_recovery_count'],1)

    def test_finish_persists_gap_instead_of_model_success_claim(self):
        old=self.prepared();project=self.service.app.store.load(old['project_id'])
        project.status='documents_delivered';self.service.app.store.save(project)
        run=self.control.create(project.id,scope='research_only',evidence_goal={'model':'X','parameter':'minimum','value':1.8,'unit':'V'})
        run['observations']=[{'action':'read_document_page','status':'executed'}];self.control.save(run)
        provider=MagicMock();provider.decide.return_value={'action':'finish','arguments':{},'reason':'claimed success'}
        result=AutonomousRunner(self.control,provider).step(run['id'])
        self.assertEqual(self.control.load(run['id'])['evidence_completion']['status'],'ended_with_gaps')
        self.assertIn('缺口',result['message'])

    def test_source_version_and_adjacent_page_have_distinct_signatures(self):
        from embedded_agent.runtime_policy import signature
        old=self.prepared();context=self.control.context(old['id'])
        with patch.object(self.service.app.documents,'document',return_value={'sha256':'v1','text_sha256':'t1'}):
            first=signature(self.control,context,'read_document_page',{'document_id':'DOC-X','page':7})
            adjacent=signature(self.control,context,'read_document_page',{'document_id':'DOC-X','page':8})
        with patch.object(self.service.app.documents,'document',return_value={'sha256':'v2','text_sha256':'t2'}):
            changed=signature(self.control,context,'read_document_page',{'document_id':'DOC-X','page':7})
        self.assertNotEqual(first,adjacent);self.assertNotEqual(first,changed)

    def test_goal_is_persisted_and_research_only(self):
        old=self.prepared();goal={'model':'NEW17','subject':'P9','predicate':'BANK2','object':'SIG3'}
        run=self.control.create(old['project_id'],scope='research_only',evidence_goal=goal)
        self.assertEqual(self.control.context(run['id'])['task_contract']['claim_target'],goal)
        with self.assertRaises(ValueError):self.control.create(old['project_id'],evidence_goal=goal)

    def test_generic_research_reads_source_without_another_model_turn(self):
        old=self.prepared();run=self.control.create(old['project_id'],scope='research_only')
        run['auto_feedback']={'status':'failed','failure_code':'source_reference','action':'record_fact','attempted_fields':{'document_id':'DOC-newchip','page':3}}
        self.control.save(run);provider=MagicMock()
        with patch.object(self.service.app.tools,'execute',return_value={'status':'passed','page':{'document_id':'DOC-newchip','page':3,'text':'real source','sha256':'fixture'}}) as execute:
            result=AutonomousRunner(self.control,provider).step(run['id'])
        provider.decide.assert_not_called();execute.assert_called_once_with('documents.page',{'document_id':'DOC-newchip','page':3,'source_view':'text'})
        self.assertEqual(result['status'],'continue');self.assertEqual(result['context']['run']['steps'],1)
        self.assertIsNone(result['context']['orchestration_state']['automatic_action'])

    def test_research_prompt_is_isolated_from_firmware_repair_instructions(self):
        old=self.prepared();run=self.control.create(old['project_id'],scope='research_only')
        model=MagicMock();ModelDecider(model).decide(self.control.context(run['id']))
        sent=model.generate.call_args.kwargs
        self.assertNotIn('draft_patch',sent['instruction'])
        self.assertIn('task_contract',sent['context'])
        self.assertIn('orchestration_state',sent['context'])
