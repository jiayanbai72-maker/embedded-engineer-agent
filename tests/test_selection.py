import unittest
import json
import test_architecture
from embedded_agent.service import EngineeringService
from embedded_agent.selection import evaluate_selection


def proposal(check):
    return {'checks':[dict(check,id='CHK-1',evidence_ids=['E1'])], 'evidence':[{'id':'E1','reviewed':True,'reviewer':'test_fixture', 'snapshot_sha256':'fixture-only','section':'test','scope_note':'synthetic test data, not real component evidence'}]}


class SelectionTests(unittest.TestCase):
    def test_budget_and_missing_prices(self):
        p=proposal({'kind':'budget','inputs':{'limit_cny':100,'shipping_cny':10,'coverage_complete':True,'parts':[{'model':'TEST','quantity':3,'unit_price_cny':40}]}})
        self.assertEqual(evaluate_selection(p)['status'],'failed')
        p['checks'][0]['inputs']['parts'][0]['unit_price_cny']=None
        self.assertEqual(evaluate_selection(p)['status'],'needs_evidence')

    def test_voltage_range_not_just_overlap(self):
        p=proposal({'kind':'voltage','inputs':{'output_min_v':3,'output_max_v':5,'input_min_v':3,'input_max_v':3.6}})
        self.assertEqual(evaluate_selection(p)['status'],'failed')

    def test_resource_and_unreviewed_evidence(self):
        p=proposal({'kind':'resource','inputs':{'resource':'PWM','available':4,'required':3}})
        self.assertEqual(evaluate_selection(p)['status'],'passed')
        p['evidence'][0]['reviewed']=False
        self.assertEqual(evaluate_selection(p)['status'],'needs_evidence')

    def test_energy_and_invalid_inputs(self):
        p=proposal({'kind':'energy','inputs':{'battery_v':3.7,'capacity_mah':2000,'usable_fraction':0.85,'reserve_fraction':0.2,'hours':48,'idle_mw':200,'active_mw':2000,'active_seconds':150}})
        self.assertEqual(evaluate_selection(p)['status'],'failed')
        p['checks'][0]['inputs']['hours']=float('nan')
        with self.assertRaises(ValueError): evaluate_selection(p)


class SelectionIntegrationTests(unittest.TestCase):
    setUp = test_architecture.ArchitectureTests.setUp
    tearDown = test_architecture.ArchitectureTests.tearDown

    def test_report_invalidates_phase_delivery_without_claiming_project_complete(self):
        service=EngineeringService(self.root)
        project=service.create('约束检查演练')
        analysis=json.loads((test_architecture.ROOT/'examples/analyst-door-monitor.json').read_text(encoding='utf-8'))
        for action,args in [('analysis',analysis),('confirm',{'confirmed':True}),('select',{'candidate_id':'PLAN-NEAR'}),('execute',{})]:
            project=service.update(project['id'],project['revision'],action,args)
        p=proposal({'kind':'resource','inputs':{'resource':'PWM','available':None,'required':3}})
        project=service.update(project['id'],project['revision'],'selection_check',{'proposal':p})
        self.assertEqual(project['status'],'selection_needs_evidence')
        self.assertNotIn('delivery',project['artifacts'])
        with self.assertRaises(ValueError): service.download(project['id'])
        self.assertEqual(EngineeringService(self.root).get(project['id'])['artifacts']['selection_check']['status'],'needs_evidence')
