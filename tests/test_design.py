"""Synthetic engineering feedback tests; these are not real part specifications."""
from copy import deepcopy
import io
import json
import unittest
from zipfile import ZipFile
import test_architecture
import test_library
from embedded_agent.service import EngineeringService
from embedded_agent.control import DecisionController


class DesignTests(unittest.TestCase):
    review=test_library.LibraryTests.review
    checked_proposal=test_library.LibraryTests.checked_proposal
    tearDown=test_library.LibraryTests.tearDown

    def setUp(self):
        test_library.LibraryTests.setUp(self)
        self.content+='ALT output range is 6.0 V to 6.0 V.\n'
        self.text.write_text(self.content,encoding='utf-8')
        path=self.root/'knowledge/official/fixture.pages.json'
        spans=json.loads(path.read_text()); spans[-1]['length']=len(self.content)-spans[-1]['offset']; path.write_text(json.dumps(spans))
        self.library.build()
        self.service=EngineeringService(self.root)
        p=self.service.create('Synthetic options feedback')
        analysis=json.loads((test_architecture.ROOT/'examples/analyst-door-monitor.json').read_text(encoding='utf-8'))
        p=self.service.update(p['id'],p['revision'],'analysis',analysis)
        self.project=self.service.update(p['id'],p['revision'],'confirm',{'confirmed':True})

    def submit(self,action,payload):
        self.project=self.service.update(self.project['id'],self.project['revision'],action,payload)
        return self.project['artifacts']['design_loop']['rounds'][-1]

    def plan(self):
        good=self.checked_proposal(); good['checks'][0]['objective_id']='VDD'
        bad=deepcopy(good)
        for field in ('output_min_v','output_max_v'):
            p=self.params.review({'document_id':'DOC-fixture','page':2,'model':'ALT-TEST','parameter':field,'value':6,'unit':'V',
                'conditions':'synthetic test only','quote':'ALT output range is 6.0 V to 6.0 V.',
                'reviewer':'test fixture','rationale':'Synthetic alternative output, not a real component','confirmed':True})
            bad['checks'][0]['inputs'][field]=6
            bad['checks'][0]['parameter_bindings'][field]={'parameter_id':p['id'],'model':p['model'],'conditions':p['conditions']}
        reqs=[r['id'] for r in self.project['artifacts']['requirements']['requirements']]
        candidates=[]
        for name,proposal in [('GOOD',good),('BAD',bad)]:
            candidates.append({'id':name,'name':name,'architecture':'synthetic source → load',
                'covers':reqs,'components':[{'role':'supply','model':name}], 'tradeoffs':['synthetic tradeoff'],
                'risks':['not hardware validated'],'assumptions':['synthetic fixture only'],'proposal':proposal})
        return {'analyst':'test fixture','scope':'synthetic voltage constraint only','rationale':'Compare independently reviewed fixture outputs',
            'objectives':[{'id':'VDD','description':'synthetic load voltage','kind':'voltage','requirement_ids':[reqs[0]],
                           'fixed_inputs':{'input_min_v':1.8,'input_max_v':3.6}}],
            'candidates':candidates,'tasks':[{'id':'DOC','question':'Which voltage bounds are supported?',
                'query':'TESTCHIP voltage','why':'Retrieve before evaluating','candidate_ids':['GOOD','BAD']}]}

    def test_real_tools_observation_drives_revision_and_preserves_history(self):
        initial=self.plan(); self.submit('design_plan',{'plan':initial})
        with self.assertRaises(ValueError): self.submit('design_evaluate',{})
        researched=self.submit('design_research',{'task_id':'DOC'})
        self.assertTrue(researched['research_results'][0]['matches'])
        round=self.submit('design_evaluate',{})
        self.assertEqual([e['report']['status'] for e in round['evaluations']],['passed','failed'])
        revised=deepcopy(initial); revised['candidates'][1]['proposal']=deepcopy(initial['candidates'][0]['proposal'])
        revised['candidates'][1]['components']=[{'role':'supply','model':'GOOD'}]
        ref=round['evaluations'][1]['report']['checks'][0]['observation_id']
        revised.update(response_to=[ref],changes=[{'candidate_id':'BAD','reason':'Replace 6 V source using observed range failure','observation_ids':[ref]}])
        self.submit('design_plan',{'plan':revised})
        self.submit('design_research',{'task_id':'DOC'}); round=self.submit('design_evaluate',{})
        self.assertEqual([e['report']['status'] for e in round['evaluations']],['passed','passed'])
        restored=EngineeringService(self.root).get(self.project['id'])
        self.assertEqual(len(restored['artifacts']['design_loop']['rounds']),2)
        self.assertEqual(restored['artifacts']['design_loop']['rounds'][0]['evaluations'][1]['report']['status'],'failed')
        self.assertNotIn('selected_plan',restored['artifacts'])

    def test_cannot_relax_targets_drop_checks_or_fabricate_observations(self):
        initial=self.plan(); self.submit('design_plan',{'plan':initial}); self.submit('design_research',{'task_id':'DOC'})
        round=self.submit('design_evaluate',{}); ref=round['evaluations'][1]['report']['checks'][0]['observation_id']
        revised=deepcopy(initial); revised.update(response_to=[ref],changes=[{'candidate_id':'BAD','reason':'fix output','observation_ids':[ref]}])
        with self.assertRaises(ValueError): self.submit('design_plan',{'plan':revised})
        revised['candidates'][1]['proposal']=deepcopy(initial['candidates'][0]['proposal'])
        revised['response_to']=['invented']
        with self.assertRaises(ValueError): self.submit('design_plan',{'plan':revised})
        revised['response_to']=[ref]; revised['objectives'][0]['fixed_inputs']['input_max_v']=7
        with self.assertRaises(ValueError): self.submit('design_plan',{'plan':revised})
        revised=deepcopy(initial); revised['candidates'][1]['proposal']['checks']=[]
        with self.assertRaises(ValueError): self.submit('design_plan',{'plan':revised})

    def test_recommendation_does_not_select_and_user_accept_exports_trace(self):
        self.submit('design_plan',{'plan':self.plan()}); self.submit('design_research',{'task_id':'DOC'})
        round=self.submit('design_evaluate',{})
        ref=round['evaluations'][0]['report']['checks'][0]['observation_id']
        with self.assertRaises(ValueError): self.submit('design_recommend',{'candidate_id':'BAD','rationale':'bad','observation_ids':[ref]})
        self.submit('design_recommend',{'candidate_id':'GOOD','rationale':'Only this output is in the supported interval','observation_ids':[ref]})
        self.assertNotIn('selected_plan',self.project['artifacts'])
        self.submit('design_accept',{'candidate_id':'GOOD','confirmed':True})
        self.assertEqual(self.project['status'],'selection_checked')
        p=self.service.update(self.project['id'],self.project['revision'],'continue_selection',{'confirmed':True})
        p=self.service.update(p['id'],p['revision'],'execute',{})
        with ZipFile(io.BytesIO(self.service.download(p['id']))) as z:
            self.assertIn('design-reasoning-history.json',z.namelist())

    def test_unknown_evidence_is_not_rejection_or_confirmed_feasibility(self):
        plan=self.plan()
        for c in plan['candidates']: c['proposal']['checks'][0].pop('parameter_bindings')
        self.submit('design_plan',{'plan':plan}); self.submit('design_research',{'task_id':'DOC'})
        round=self.submit('design_evaluate',{})
        self.assertTrue(all(e['report']['status']=='needs_evidence' for e in round['evaluations']))
        self.assertTrue(round['gaps'][1]['note'])
        ref=round['evaluations'][0]['report']['checks'][0]['observation_id']
        round=self.submit('design_recommend',{'candidate_id':'GOOD','rationale':'Conditional research direction only','observation_ids':[ref]})
        self.assertEqual(round['recommendation']['status'],'conditional')
        with self.assertRaises(ValueError): self.submit('design_accept',{'candidate_id':'GOOD','confirmed':True})

    def test_controller_executes_plan_research_check_without_confirmation_power(self):
        controller=DecisionController(self.service); run=controller.create(self.project['id'])
        for i,(action,args) in enumerate([('design_plan',{'plan':self.plan()}),('design_research',{'task_id':'DOC'}),('design_evaluate',{})]):
            ctx=controller.context(run['id'])
            decision={'id':f'D{i}','project_revision':ctx['project']['revision'],'action':action,'arguments':args,
                'rationale':'Synthetic analyst decision using prior observation','expected':'Traceable tool feedback','source':'test fixture'}
            controller.submit(run['id'],ctx['run']['revision'],decision); run=controller.tick(run['id'])
            self.assertEqual(run['observations'][-1]['status'],'executed')
        self.assertTrue(run['observations'][-1]['tool_result']['evaluations'])
        self.assertNotIn('design_accept',controller.context(run['id'])['allowed_actions'])
