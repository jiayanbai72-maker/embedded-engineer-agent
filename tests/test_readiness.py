import io
import json
import unittest
from zipfile import ZipFile
import test_control
from embedded_agent.readiness import assess, capabilities


class ReadinessTests(unittest.TestCase):
    setUp = test_control.ControlTests.setUp
    tearDown = test_control.ControlTests.tearDown
    prepared = test_control.ControlTests.prepared

    def test_offline_scope_does_not_claim_hardware_or_agent_complete(self):
        run = self.prepared()
        p = self.service.get(run['project_id'])
        r = assess(p)
        self.assertIn('build', r['scope_blockers'])
        self.assertIn('verification', r['scope_blockers'])
        self.assertNotIn('hardware', r['scope_blockers'])
        self.assertFalse(r['hardware_verified'])
        self.assertFalse(r['complete_agent'])
        self.assertEqual(next(x for x in r['checks'] if x['id'] == 'quotes')['status'], 'deferred')

    def test_draft_failure_blocks_offline_delivery_and_stale_pass_is_not_reused(self):
        from embedded_agent.draft_verification import source_hash
        run=self.prepared();p=self.service.app.store.load(run['project_id'])
        files={'app.c':'void step(void){}'}
        p.artifacts['engineering_draft']={k:{'files':dict(files)} for k in ('interfaces','circuit','firmware')}
        p.artifacts['draft_verification']={'source_sha256':source_hash(files),'mcu_compile':{'status':'passed'},'host_tests':{'status':'failed'}}
        view=self.service.view(p);report=assess(view)
        self.assertEqual(view['verification']['mcu_object_compilation'],'passed')
        self.assertEqual(view['verification']['host_tests'],'failed')
        self.assertIn('draft_host_tests',report['scope_blockers'])
        self.assertNotIn('hardware',report['scope_blockers'])
        p.artifacts['engineering_draft']['firmware']['files']['app.c']='void step(void){ /* changed */ }'
        report=assess(self.service.view(p))
        self.assertIn('draft_mcu_compile',report['scope_blockers'])
        self.assertEqual(next(c for c in report['checks'] if c['id']=='draft_mcu_compile')['status'],'not_run')

    def test_no_fake_compiler_probe_or_hardware_detection(self):
        self.prepared()
        c = capabilities(self.service.app)
        items = {x['id']: x for x in c['items']}
        self.assertIn(items['hardware_execution']['status'], ('needs_configuration', 'receive_only_available'))
        self.assertEqual(items['autonomous_decision']['status'], 'not_connected')
        self.assertIn(items['armcc_build']['status'], ('configured_unverified', 'needs_configuration'))

    def test_new_export_has_frozen_assessment_and_stable_download(self):
        run = self.prepared()
        p = self.service.app.store.load(run['project_id'])
        p.artifacts['decision']['actions'] = ['export_documents']
        p.status = 'ready_delivery'
        self.service.app.store.save(p)
        view = self.service.update(p.id, p.revision, 'execute', {})
        raw = self.service.download(p.id)
        self.assertEqual(raw, self.service.download(p.id))
        with ZipFile(io.BytesIO(raw)) as z:
            report = json.loads(z.read('delivery-assessment.json'))
        self.assertFalse(report['hardware_verified'])
        self.assertEqual(report['offline_status'], 'ready_for_scoped_delivery')
        self.assertEqual(report, view['artifacts']['delivery_assessment'])


if __name__ == '__main__': unittest.main()
