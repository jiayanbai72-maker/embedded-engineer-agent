import unittest
from unittest.mock import MagicMock,patch
from embedded_agent.research_report import evaluate
from embedded_agent.autonomy import AutonomousRunner
from embedded_agent.model_context import prepare
import test_control


class PwmReportTests(unittest.TestCase):
    def fixture(self):
        facts=[];mappings=[]
        for n in range(3):
            pin='PA'+str(n);signal='TIM2_CH'+str(n+1)
            facts.extend([dict(id='m'+str(n),valid=True,model='SYNTHETIC',subject=pin,predicate='AF2',object=signal),dict(id='p'+str(n),valid=True,model='SYNTHETIC',subject=pin,predicate='package',object='SYNTHETIC32')])
            mappings.append(dict(pin=pin,af='AF2',signal=signal,fact_id='m'+str(n),package_fact_id='p'+str(n)))
        facts.append(dict(id='voice',valid=True,model='SYNTHETIC',subject='PA9',predicate='AF4',object='USART1_TX'))
        facts.extend([dict(id='voice-package',valid=True,model='SYNTHETIC',subject='PA9',predicate='package',object='SYNTHETIC32'),dict(id='voice-rx',valid=True,model='SYNTHETIC',subject='PA10',predicate='AF4',object='USART1_RX'),dict(id='voice-rx-package',valid=True,model='SYNTHETIC',subject='PA10',predicate='package',object='SYNTHETIC32')])
        return dict(model='SYNTHETIC',package='SYNTHETIC32',summary='Synthetic evidence binding only',mappings=mappings,voice_pins=[dict(pin='PA9',af='AF4',signal='USART1_TX',fact_id='voice',package_fact_id='voice-package'),dict(pin='PA10',af='AF4',signal='USART1_RX',fact_id='voice-rx',package_fact_id='voice-rx-package')],unresolved=[]),facts

    def test_voice_requires_package_and_matching_tx_rx(self):
        data,facts=self.fixture();data['voice_pins'][0]['package_fact_id']=None
        self.assertEqual(evaluate(data,facts)['status'],'needs_evidence')

    def test_deferred_hardware_work_is_not_claimed_as_passed(self):
        data,facts=self.fixture();data['deferred']=['Hardware power validation not run']
        report=evaluate(data,facts)
        self.assertEqual(report['status'],'passed');self.assertFalse(report['hardware_verified'])
        self.assertEqual(report['deferred'],data['deferred']);self.assertEqual(report['gaps'],[])
        data['unresolved']=['PWM register timing still not verified']
        report=evaluate(data,facts)
        self.assertEqual(report['status'],'passed')
        self.assertEqual(report['model_concerns'],data['unresolved'])
        data,facts=self.fixture();data['voice_pins']=data['voice_pins'][:1]
        self.assertEqual(evaluate(data,facts)['status'],'needs_evidence')

    def test_three_distinct_bound_relations(self):
        data,facts=self.fixture();report=evaluate(data,facts)
        self.assertEqual(report['status'],'passed');self.assertFalse(report['hardware_verified'])

    def test_physical_pin_is_from_grid_evidence_not_model_prose(self):
        data,facts=self.fixture();data['summary']='Model incorrectly claims physical pin 999'
        facts[1]['pin_number']='8';data['mappings'][0]['physical_pin']='999'
        report=evaluate(data,facts)
        self.assertEqual(report['mappings'][0]['physical_pin'],'8')
        self.assertNotIn('999',report['summary'])

    def test_package_voice_or_invalid_sources_block_pass(self):
        for change in ('package','voice','stale','duplicate'):
            data,facts=self.fixture()
            if change=='package':data['mappings'][0]['package_fact_id']=None
            if change=='voice':data['voice_pins']=[]
            if change=='stale':facts[0]['valid']=False
            if change=='duplicate':data['mappings'][1]['pin']='PA0'
            self.assertEqual(evaluate(data,facts)['status'],'needs_evidence',change)


class PwmRunTests(unittest.TestCase):
    setUp=test_control.ControlTests.setUp
    tearDown=test_control.ControlTests.tearDown
    prepared=test_control.ControlTests.prepared
    def test_repeated_read_reuses_receipt_then_requires_conclusion(self):
        old=self.prepared();p=self.service.app.store.load(old['project_id']);p.status='documents_delivered';self.service.app.store.save(p)
        r=self.control.create(p.id,max_steps=8,max_repairs=0,scope='research_only',task='pwm_review')
        receipt=dict(action='read_document_page',status='executed',work_signature='same',tool_result={'status':'passed','page':{'text':'Exact original cached page'}})
        r['receipts']={'first':receipt};r['observations']=[receipt];r['steps']=1;self.control.save(r)
        provider=MagicMock();provider.decide.return_value={'action':'read_document_page','arguments':{'document_id':'DOC-synthetic','page':1},'reason':'Read relevant page'}
        runner=AutonomousRunner(self.control,provider)
        with patch('embedded_agent.autonomy.signature',return_value='same'),patch.object(self.service.app.tools,'execute') as execute:
            result=runner.step(r['id']);self.assertEqual(result['status'],'continue')
            view=prepare(self.control.context(r['id']))
            self.assertEqual(view['run']['observations'][-1]['tool_result']['page']['text'],'Exact original cached page')
            runner.step(r['id']);execute.assert_not_called()
        self.assertEqual(self.control.load(r['id'])['steps'],1)
        self.assertEqual(self.control.context(r['id'])['allowed_actions'],['conclude_research'])

    def test_report_completes_run_without_changing_delivered_project(self):
        old=self.prepared();p=self.service.app.store.load(old['project_id']);p.status='documents_delivered';self.service.app.store.save(p)
        before=self.service.get(p.id)
        r=self.control.create(p.id,max_steps=2,max_repairs=0,scope='research_only',task='pwm_review')
        r['steps']=1;self.control.save(r)
        self.assertEqual(self.control.context(r['id'])['allowed_actions'],['conclude_research'])
        data=dict(model='UNKNOWN',package='UNKNOWN',summary='Cannot prove mapping yet',mappings=[],voice_pins=[],unresolved=['No verified source'])
        self.control.submit(r['id'],r['revision'],dict(id='report',project_revision=p.revision,action='conclude_research',arguments=data,rationale='Stop with explicit gaps',expected='Save honest report',source='offline_test'))
        final=self.control.advance(r['id'])
        self.assertEqual(final['status'],'complete')
        self.assertEqual(final['research_report']['status'],'needs_evidence')
        self.assertEqual(self.service.get(p.id),before)
