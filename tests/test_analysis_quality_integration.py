import unittest
import test_architecture
from test_control import sample_module
from embedded_agent.service import EngineeringService
from embedded_agent.analysis_quality import validate


class AnalysisQualityIntegrationTests(unittest.TestCase):
    setUp = test_architecture.ArchitectureTests.setUp
    tearDown = test_architecture.ArchitectureTests.tearDown

    def test_rejected_analysis_does_not_advance_and_corrected_resubmission_saves(self):
        service=EngineeringService(self.root)
        description='每通道每秒10000样本、8通道、每样本16位、连续保存30天、仅16MB存储'
        p=service.create(description)
        payload=sample_module().authored_analysis()
        payload['requirements']['requirements'][0]['acceptance']='30天所需原始容量约395.5 GiB'
        before=service.get(p['id'])
        with self.assertRaisesRegex(ValueError,'requirements.*acceptance'):
            service.update(p['id'],p['revision'],'analysis',payload)
        self.assertEqual(service.get(p['id']),before)
        payload['requirements']['requirements'][0]['acceptance']='30天所需原始容量约386.238 GiB'
        saved=service.update(p['id'],p['revision'],'analysis',payload)
        self.assertEqual(saved['status'],'needs_input')
        self.assertEqual(saved['artifacts']['analysis_quality']['numeric_reference']['capacity_B'],414720000000)

    def test_known_error_paths_remain_field_specific(self):
        req={'requirements':[], 'questions':[{'blocking':True,'question':'是否从最后一次有效新序号指令的时刻起算？'}]}
        with self.assertRaisesRegex(ValueError,r'questions\[0\]'):
            validate('重放包不能续命',req,{})

    def test_legacy_saved_analysis_is_rechecked_before_confirmation(self):
        service=EngineeringService(self.root)
        p=service.create('每通道每秒10000样本、8通道、每样本16位、连续保存30天、仅16MB存储')
        p=service.update(p['id'],p['revision'],'analysis',sample_module().authored_analysis())
        legacy=service.app.store.load(p['id'])
        legacy.artifacts['requirements']['requirements'][0]['acceptance']='30天所需原始容量约395.5 GiB'
        legacy.artifacts.pop('analysis_quality',None)
        service.app.store.save(legacy)
        before=service.get(p['id'])
        with self.assertRaisesRegex(ValueError,'容量换算'):
            service.update(p['id'],p['revision'],'confirm',{'confirmed':True})
        self.assertEqual(service.get(p['id']),before)

if __name__=='__main__':unittest.main()
