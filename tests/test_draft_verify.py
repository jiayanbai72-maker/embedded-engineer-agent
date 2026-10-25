import unittest
from copy import deepcopy
from unittest.mock import patch
import test_draft_workflow as fixtures
from embedded_agent import draft
from embedded_agent.control import DecisionController
from embedded_agent.autonomy import AutonomousRunner
from embedded_agent.draft_verification import source_hash,verify
from pathlib import Path

class VerifyTests(fixtures.test_power.PowerIntegrationTests):
    def prepared(self):
        s,p=self.ready()
        p=s.update(p['id'],p['revision'],'power_estimate',{'candidate_id':'PLAN-NEAR','model':fixtures.test_power.model()})
        p=s.update(p['id'],p['revision'],'proceed_estimated_design',{'candidate_id':'PLAN-NEAR','confirmed':True,'accept_open_items':True,'rationale':'fixture'})
        p=s.update(p['id'],p['revision'],'start_draft',{'confirmed':True})
        for stage in draft.STAGES:
            arg=fixtures.payload(stage)
            if stage=='firmware':arg['files']['test_motion.c']='#include <assert.h>\nint main(void){assert(1);return 0;}'
            p=s.update(p['id'],p['revision'],'draft_artifacts',arg)
        return s,p

    def test_failed_tool_feedback_repairs_and_retests_before_export(self):
        s,p=self.prepared();control=DecisionController(s);run=control.create(p['id'])
        files=deepcopy(p['artifacts']['engineering_draft']['firmware']['files'])
        fixed=deepcopy(files);fixed['motion.c']='void motion_stop(void) { /* corrected fixture */ }'
        class Provider:
            calls=0
            def decide(self,ctx):
                self.calls+=1
                if self.calls==2:
                    assert ctx['project']['artifacts']['draft_verification']['host_tests']['log']=='assertion failed'
                    return {'action':'draft_artifacts','arguments':dict(fixtures.payload('firmware'),files=fixed),'reason':'repair actual failure'}
                return {'action':'draft_verify','arguments':{'cpu':'Cortex-M0plus'},'reason':'run real adapters'}
        reports=[{'status':'failed','source_sha256':source_hash(files),'host_tests':{'status':'failed','log':'assertion failed'}},
                 {'status':'passed','source_sha256':source_hash(fixed),'host_tests':{'status':'passed'}}]
        with patch('embedded_agent.draft_verification.verify',side_effect=reports) as tool:
            runner=AutonomousRunner(control,Provider())
            runner.step(run['id'])
            p=s.get(p['id'])
            with self.assertRaises(ValueError):s.update(p['id'],p['revision'],'execute',{})
            bad=dict(fixtures.payload('firmware'),files={'motion.c':'void motion_stop(void){}'})
            with self.assertRaisesRegex(ValueError,'原失败测试'):s.update(p['id'],p['revision'],'draft_artifacts',bad)
            runner.step(run['id']);runner.step(run['id'])
            self.assertEqual(tool.call_count,2)
        current=s.get(p['id']);self.assertEqual(current['status'],'draft_verified')
        self.assertEqual(control.load(run['id'])['repairs'],1)
        self.assertEqual(current['verification']['hardware'],'not_run')
        current=s.update(current['id'],current['revision'],'execute',{})
        self.assertEqual(current['status'],'documents_delivered')

    def test_small_patch_requires_source_hash_and_unique_text_and_keeps_tests(self):
        import hashlib
        s,p=self.prepared();files=p['artifacts']['engineering_draft']['firmware']['files'];body=files['motion.c']
        patch_args={'file':'motion.c','sha256':hashlib.sha256(body.encode()).hexdigest(),'replacements':[{'old':body,'new':'void motion_stop(void) { /* fixture replacement */ }'}],'rationale':'fixture'}
        with self.assertRaises(ValueError):s.update(p['id'],p['revision'],'draft_patch',dict(patch_args,sha256='wrong'))
        with self.assertRaises(ValueError):s.update(p['id'],p['revision'],'draft_patch',dict(patch_args,file='test_motion.c'))
        with self.assertRaises(ValueError):s.update(p['id'],p['revision'],'draft_patch',dict(patch_args,replacements=[{'old':'not found','new':'x'}]))
        changed=s.update(p['id'],p['revision'],'draft_patch',patch_args)
        self.assertEqual(changed['artifacts']['engineering_draft']['firmware']['files']['test_motion.c'],files['test_motion.c'])
        self.assertEqual(changed['artifacts']['engineering_draft']['firmware']['files']['motion.c'],patch_args['replacements'][0]['new'])

    def test_missing_tests_rejected_and_hash_changes(self):
        with self.assertRaisesRegex(ValueError,'test_'):verify(self.root,{'motion.c':'int x;'},'Cortex-M0plus')
        self.assertNotEqual(source_hash({'a.c':'int a;'}),source_hash({'a.c':'int b;'}))
