import unittest
from unittest.mock import MagicMock
import test_control
from embedded_agent.autonomy import AutonomousRunner
from embedded_agent.model_context import prepare,encoded

class ResearchRestartTests(unittest.TestCase):
    setUp=test_control.ControlTests.setUp
    tearDown=test_control.ControlTests.tearDown
    prepared=test_control.ControlTests.prepared

    def test_delivered_research_uses_provider_and_preserves_project(self):
        original=self.prepared()
        project=self.service.app.store.load(original['project_id'])
        project.status='documents_delivered';self.service.app.store.save(project)
        before=self.service.get(project.id)
        run=self.control.create(project.id,max_steps=8,max_repairs=0,scope='research_only')
        context=self.control.context(run['id'])
        self.assertNotIn('finish',context['allowed_actions'])
        self.assertNotIn('design_plan',context['allowed_actions'])
        self.assertNotIn('execute',context['allowed_actions'])
        provider=MagicMock()
        provider.decide.return_value=dict(kind='decision',action='search_documents',arguments={'query':'voltage'},rationale='Read existing original evidence before deciding.',expected='Return real references.')
        result=AutonomousRunner(self.control,provider).step(run['id'])
        provider.decide.assert_called_once()
        self.assertEqual(result['context']['run']['observations'][-1]['action'],'search_documents')
        self.assertIn('finish',result['context']['allowed_actions'])
        self.assertEqual(self.service.get(project.id),before)

    def test_research_context_excludes_large_firmware_and_history(self):
        context={'run':{'scope':'research_only','observations':[]},'project':{'id':'fixture','revision':1,'status':'documents_delivered','description':'Check official voltage evidence','artifacts':{'engineering_draft':{'files':{'main.c':'x'*300000}},'draft_regression_history':['y'*300000],'requirements':{'supply':'battery'},'design_loop':{'rounds':[{'number':3,'gaps':['voltage needs evidence'],'plan':{'candidates':[]},'evaluations':[]}]}}},'allowed_actions':['research_documents']}
        original=encoded(context)
        view=prepare(context)
        self.assertLess(len(encoded(view)),10000)
        self.assertEqual(view['research_focus']['gaps'],['voltage needs evidence'])
        self.assertNotIn('engineering_draft',view['project']['artifacts'])
        self.assertEqual(encoded(context),original)

    def test_source_excerpts_remain_explicit_and_do_not_mutate_receipts(self):
        pages=[{'document_id':'DOC-fixture','page':n,'text':'z'*16000,'sha256':'original-hash'} for n in range(1,6)]
        context={'run':{'scope':'research_only','observations':[{'tool_result':{'research':{'original_pages':pages}}}]},'project':{'artifacts':{}}}
        view=prepare(context)
        research=view['run']['observations'][-1]['tool_result']['research']
        self.assertEqual(len(research['original_pages']),2)
        self.assertEqual(research['omitted_original_page_count'],3)
        self.assertTrue(research['original_pages'][0]['text_truncated'])
        self.assertEqual(len(pages[0]['text']),16000)

    def test_failed_parameter_feedback_and_research_budget_are_explicit(self):
        context={'run':{'scope':'research_only','observations':[{'action':'record_parameter','status':'rejected','tool_result':{'status':'failed','reason':'引用不匹配'}},{'action':'read_document_page','tool_result':{}}]},'project':{'artifacts':{}},'limits':{'remaining_repairs':0,'remaining_steps':3},'registered_parameters':[]}
        view=prepare(context)
        self.assertNotIn('remaining_repairs',view['limits'])
        self.assertEqual(view['limits']['remaining_steps'],3)
        self.assertEqual(view['run']['observations'][0]['tool_outcome']['reason'],'引用不匹配')
        self.assertEqual(view['registered_parameters'],[])

if __name__=='__main__':unittest.main()
