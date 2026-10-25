import io
import json
import unittest
from copy import deepcopy
from zipfile import ZipFile
import test_architecture
import test_library
from embedded_agent.power import evaluate_power
from embedded_agent.service import EngineeringService
from embedded_agent.control import DecisionController

def model():
    return {'analyst':'synthetic fixture','scope':'Synthetic whole-load budget','schedule_basis':'synthetic 10 hour window',
      'power_boundary':'whole_load_bus','target_hours':10,'reserve_fraction':0,
      'battery':{'voltage_v':{'typical':5,'conservative':5},'capacity_mah':{'typical':1000,'conservative':1000},
                 'usable_fraction':{'typical':1,'conservative':1},'basis':'synthetic energy 5Wh'},
      'conversion_efficiency':{'typical':1,'conservative':1},'battery_overhead_mw':{'typical':0,'conservative':0},
      'states':[{'name':'idle','duration_s':{'typical':'remaining','conservative':'remaining'},
                 'load_mw':{'typical':100,'conservative':200},'source_type':'assumption','basis':'synthetic test values, not actual hardware'}],
      'peak':{'load_peak_ma':1000,'supply_limit_ma':500,'basis':'same synthetic 5V load rail, no transient test'}}

class PowerTests(unittest.TestCase):
    def test_analytical_energy_and_independent_peak(self):
        result=evaluate_power(model())
        self.assertEqual(result['scenarios']['typical']['estimated_hours'],50)
        self.assertEqual(result['scenarios']['conservative']['estimated_hours'],25)
        self.assertEqual(result['status'],'estimated_meets')
        self.assertEqual(result['peak']['status'],'estimated_shortfall')
        self.assertEqual(result['hardware'],'not_run')

    def test_losses_reserve_and_high_power_shortfall(self):
        m=model(); m['reserve_fraction']=0.2
        m['conversion_efficiency']={'typical':0.5,'conservative':0.5}
        m['states'][0]['load_mw']={'typical':1000,'conservative':2000}
        result=evaluate_power(m)
        self.assertEqual(result['scenarios']['typical']['available_wh'],4)
        self.assertEqual(result['scenarios']['typical']['required_wh'],20)
        self.assertEqual(result['scenarios']['typical']['estimated_hours'],2)
        self.assertEqual(result['status'],'estimated_shortfall')

    def test_missing_estimates_are_not_zero(self):
        m=model(); m['states'][0]['load_mw']['conservative']=None
        self.assertEqual(evaluate_power(m)['status'],'insufficient_data')

    def test_overlapping_incomplete_or_nonconservative_schedules_rejected(self):
        m=model(); m['states'].append(deepcopy(m['states'][0])); m['states'][1]['name']='second'
        with self.assertRaises(ValueError): evaluate_power(m)
        m=model(); m['states'][0]['duration_s']={'typical':36001,'conservative':36001}
        with self.assertRaises(ValueError): evaluate_power(m)
        m=model(); m['states'][0]['load_mw']['conservative']=50
        with self.assertRaises(ValueError): evaluate_power(m)
        m=model(); m['battery']['capacity_mah']['typical']=float('nan')
        with self.assertRaises(ValueError): evaluate_power(m)

class PowerIntegrationTests(unittest.TestCase):
    setUp=test_architecture.ArchitectureTests.setUp
    tearDown=test_architecture.ArchitectureTests.tearDown

    def ready(self):
        service=EngineeringService(self.root); p=service.create('Power estimate fixture')
        analysis=json.loads((test_architecture.ROOT/'examples/analyst-door-monitor.json').read_text(encoding='utf-8'))
        for op,args in [('analysis',analysis),('confirm',{'confirmed':True}),('select',{'candidate_id':'PLAN-NEAR'})]:
            p=service.update(p['id'],p['revision'],op,args)
        return service,p

    def test_estimate_does_not_approve_hardware_or_budget_and_provisional_export_is_explicit(self):
        s,p=self.ready()
        p=s.update(p['id'],p['revision'],'power_estimate',{'candidate_id':'PLAN-NEAR','model':model()})
        with self.assertRaises(ValueError): s.update(p['id'],p['revision'],'proceed_estimated_design',{'candidate_id':'PLAN-NEAR','confirmed':True})
        p=s.update(p['id'],p['revision'],'proceed_estimated_design',{'candidate_id':'PLAN-NEAR','confirmed':True,'accept_open_items':True,'rationale':'Synthetic preliminary design only; peak shortfall explicitly remains open'})
        self.assertEqual(p['status'],'preliminary_design')
        self.assertEqual(p['artifacts']['preliminary_acceptance']['budget_status'],'deferred_pending_quotes')
        self.assertNotIn('proceed_estimated_design',DecisionController(s).context(DecisionController(s).create(p['id'])['id'])['allowed_actions'])
        p=s.update(p['id'],p['revision'],'execute',{})
        with ZipFile(io.BytesIO(s.download(p['id']))) as z:
            self.assertIn('power-estimates.json',z.namelist())
            self.assertIn('preliminary-design-scope.json',z.namelist())
            self.assertIn('初步设计',z.read('README.md').decode())

    def test_changed_estimate_invalidates_old_delivery_and_restores_after_restart(self):
        s,p=self.ready()
        p=s.update(p['id'],p['revision'],'execute',{})
        p=s.update(p['id'],p['revision'],'power_estimate',{'candidate_id':'PLAN-NEAR','model':model()})
        with self.assertRaises(ValueError): s.download(p['id'])
        self.assertNotIn('delivery',p['artifacts'])
        self.assertEqual(EngineeringService(self.root).get(p['id'])['artifacts']['power_estimates']['PLAN-NEAR']['report']['hardware'],'not_run')

class PowerSourceTests(unittest.TestCase):
    setUp=test_library.LibraryTests.setUp
    tearDown=test_library.LibraryTests.tearDown
    ready=PowerIntegrationTests.ready

    def test_estimate_citation_checked_and_changed_source_blocks_preliminary_acceptance(self):
        service,p=self.ready(); m=model()
        m['states'][0]['source_type']='datasheet_estimate'
        m['states'][0]['sources']=[{'document_id':'DOC-fixture','page':2,'quote':'Supply voltage ranges from 1.8 V to 3.6 V.'}]
        p=service.update(p['id'],p['revision'],'power_estimate',{'candidate_id':'PLAN-NEAR','model':m})
        self.assertEqual(p['artifacts']['power_estimates']['PLAN-NEAR']['report']['source_references'][0]['page'],2)
        self.source.write_bytes(b'changed')
        with self.assertRaises(ValueError):
            service.update(p['id'],p['revision'],'proceed_estimated_design',{'candidate_id':'PLAN-NEAR','confirmed':True,'accept_open_items':True,'rationale':'test fixture'})

    def test_invented_or_absent_datasheet_citation_rejected(self):
        service,p=self.ready(); m=model(); m['states'][0]['source_type']='datasheet_estimate'
        with self.assertRaises(ValueError): service.update(p['id'],p['revision'],'power_estimate',{'candidate_id':'PLAN-NEAR','model':m})
        m['states'][0]['sources']=[{'document_id':'DOC-fixture','page':2,'quote':'Invented source text not found in page'}]
        with self.assertRaises(ValueError): service.update(p['id'],p['revision'],'power_estimate',{'candidate_id':'PLAN-NEAR','model':m})
