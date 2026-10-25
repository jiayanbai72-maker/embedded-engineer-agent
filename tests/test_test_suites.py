import hashlib
import io
import json
import unittest
from unittest.mock import Mock, patch
from zipfile import ZipFile
from pathlib import Path
from embedded_agent import test_suites
from embedded_agent.autonomy import AutonomousRunner, ModelDecider
from embedded_agent.control import DecisionController
from embedded_agent.draft_verification import source_hash
import test_draft_verify as fixtures

class SuiteIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.VerifyTests();self.fixture.setUp()
        self.root=self.fixture.root
        self.service,self.project=self.fixture.prepared()

    def tearDown(self):self.fixture.tearDown()

    def attach(self):
        folder=self.root/'runtime/boundary-audit/20261017-220353';folder.mkdir(parents=True)
        body='#include <assert.h>\nint main(void){assert(1);return 0;}'
        (folder/'edge.c').write_text(body,encoding='utf-8')
        (folder/'report.json').write_text(json.dumps({'project_id':self.project['id'],
            'cases':[{'id':'edge','test_sha256':hashlib.sha256(body.encode()).hexdigest()}]}),encoding='utf-8')
        self.project=self.service.update(self.project['id'],self.project['revision'],'draft_tests',
                                         {'suite_id':folder.name,'confirmed':True})
        return folder

    def result(self,status='passed'):
        f=self.service.get(self.project['id'])['artifacts']['engineering_draft']['firmware']['files']
        return {'status':status,'source_sha256':source_hash(f),'mcu_compile':{'status':'passed','cpu':'Cortex-M0plus'},
                'host_tests':{'status':status,'log':'original fixture' if status=='passed' else 'assertion failed'}}

    def test_audit_import_rejects_path_wrong_project_and_tampered_cases(self):
        folder=self.attach()
        self.assertEqual(len(test_suites.available(self.root,self.project['id'])),1)
        with self.assertRaises(ValueError):test_suites.load_audit(self.root,self.project['id'],'../outside')
        with self.assertRaises(ValueError):test_suites.load_audit(self.root,'different',folder.name)
        (folder/'edge.c').write_text('changed',encoding='utf-8')
        with self.assertRaises(ValueError):test_suites.load_audit(self.root,self.project['id'],folder.name)

    def test_extra_failure_blocks_export_even_when_original_passed(self):
        self.attach()
        with patch('embedded_agent.draft_verification.verify',side_effect=[self.result(),self.result('failed')]):
            p=self.service.update(self.project['id'],self.project['revision'],'draft_verify',{'cpu':'Cortex-M0plus'})
        self.assertEqual(p['status'],'draft_verification_failed')
        self.assertEqual(p['artifacts']['draft_verification']['original_host_tests']['status'],'passed')
        with self.assertRaises(ValueError):self.service.update(p['id'],p['revision'],'execute',{})

    def test_stale_suite_report_cannot_unlock_delivery(self):
        self.attach()
        p=self.service.app.store.load(self.project['id']);p.status='draft_verified'
        p.artifacts['draft_verification']=self.result()
        self.service.app.store.save(p)
        with self.assertRaisesRegex(ValueError,'扩展测试'):self.service.update(p.id,p.revision,'execute',{})

    def test_changed_original_test_cannot_be_revalidated(self):
        self.attach()
        p=self.service.app.store.load(self.project['id'])
        p.artifacts['engineering_draft']['firmware']['files']['test_motion.c']='int main(void){return 0;}'
        self.service.app.store.save(p)
        with patch('embedded_agent.draft_verification.verify') as compiler:
            with self.assertRaisesRegex(ValueError,'原测试发生变化'):
                self.service.update(p.id,p.revision,'draft_verify',{'cpu':'Cortex-M0plus'})
            compiler.assert_not_called()

    def test_suite_digest_mismatch_cannot_reuse_passed_report(self):
        self.attach();p=self.service.get(self.project['id']);suite=p['artifacts']['draft_test_suite']
        report=self.result();report['supplemental_tests']={'status':'passed','suite_sha256':'other'}
        files=p['artifacts']['engineering_draft']['firmware']['files']
        self.assertFalse(test_suites.current(report,files,suite))

    def test_model_repairs_then_program_retests_packages_finishes_without_more_calls(self):
        self.attach()
        original=self.service.get(self.project['id'])['artifacts']['engineering_draft']['firmware']['files']['test_motion.c']
        with patch('embedded_agent.draft_verification.verify',side_effect=[self.result(),self.result('failed')]):
            p=self.service.update(self.project['id'],self.project['revision'],'draft_verify',{'cpu':'Cortex-M0plus'})
        controller=DecisionController(self.service);run=controller.create(p['id'])
        body=p['artifacts']['engineering_draft']['firmware']['files']['motion.c']
        model=Mock();model.generate.return_value={'patches':[{'file':'motion.c','sha256':hashlib.sha256(body.encode()).hexdigest(),
            'replacements':[{'old':body,'new':'void motion_stop(void) { /* model fixture */ }'}]}],'rationale':'fixture-specific repair'}
        runner=AutonomousRunner(controller,ModelDecider(model))
        self.assertEqual(runner.step(run['id'])['status'],'continue')
        with patch('embedded_agent.draft_verification.verify',side_effect=lambda *a:self.result()):
            self.assertEqual(runner.step(run['id'])['status'],'continue')
        self.assertEqual(runner.step(run['id'])['status'],'continue')
        self.assertEqual(runner.step(run['id'])['status'],'complete')
        self.assertEqual(model.generate.call_count,1)
        sent=model.generate.call_args.kwargs
        self.assertEqual(sent['role'],'focused_repair')
        self.assertIn('edge',sent['context']['additional_frozen_tests'])
        p=self.service.get(p['id']);self.assertEqual(p['status'],'documents_delivered')
        self.assertEqual(p['artifacts']['engineering_draft']['firmware']['files']['test_motion.c'],original)
        with ZipFile(io.BytesIO(self.service.download(p['id']))) as z:
            self.assertIn('additional-verification/tests/edge.c',z.namelist())
            self.assertEqual(json.loads(z.read('draft-verification.json'))['supplemental_tests']['status'],'passed')

if __name__=='__main__':unittest.main()
