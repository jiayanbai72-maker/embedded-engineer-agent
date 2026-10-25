import io
import json
from zipfile import ZipFile
import unittest
from copy import deepcopy
from embedded_agent import draft
from embedded_agent.control import DecisionController
import test_power


def payload(stage):
    files={'interfaces':{'interfaces.md':'# Synthetic interface\nPWM pin TBD; no hardware verification.'},
           'circuit':{'connections.json':json.dumps({'connections':[{'from':'U1.PWM_TBD','to':'J1.signal','signal':'PWM; voltage TBD','status':'unverified'}]})},
           'firmware':{'motion.c':'void motion_stop(void) {}','README.md':'Synthetic source only; no target build.'}}[stage]
    return {'stage':stage,'files':files,'rationale':'synthetic fixture','assumptions':['Pin pending review'],'open_items':['Build and hardware not run']}

class DraftTests(unittest.TestCase):
    def test_order_and_path_and_missing_artifacts(self):
        with self.assertRaises(ValueError):draft.save({},payload('firmware'))
        p=payload('interfaces');p['files']={'../escape.md':'x'}
        with self.assertRaises(ValueError):draft.save({},p)
        with self.assertRaises(ValueError):draft.save({'interfaces':{}},dict(payload('circuit'),files={'notes.md':'no connections'}))

    def test_draft_dependencies_and_inert_svg(self):
        state={}
        for stage in draft.STAGES:state=draft.save(state,payload(stage))
        self.assertIn('<path',state['circuit']['files']['connections.svg'])
        self.assertEqual(state['firmware']['firmware_build'],'not_run')
        revised=draft.save(state,payload('interfaces'))
        self.assertNotIn('circuit',revised);self.assertNotIn('firmware',revised)
        p=payload('circuit');p['files']['evil.svg']='<script>alert(1)</script>'
        saved=draft.save(revised,p)
        self.assertNotIn('evil.svg',saved['circuit']['files'])

class IntegrationTests(test_power.PowerIntegrationTests):
    def test_reopen_research_package_and_export_real_drafts(self):
        s,p=self.ready()
        p=s.update(p['id'],p['revision'],'power_estimate',{'candidate_id':'PLAN-NEAR','model':test_power.model()})
        p=s.update(p['id'],p['revision'],'proceed_estimated_design',{'candidate_id':'PLAN-NEAR','confirmed':True,'accept_open_items':True,'rationale':'fixture draft'})
        p=s.update(p['id'],p['revision'],'execute',{})
        requirements=deepcopy(p['artifacts']['requirements'])
        with self.assertRaises(ValueError):s.update(p['id'],p['revision'],'start_draft',{})
        p=s.update(p['id'],p['revision'],'start_draft',{'confirmed':True})
        with self.assertRaises(ValueError):s.update(p['id'],p['revision'],'execute',{})
        for stage in draft.STAGES:
            controller=DecisionController(s);ctx=controller.context(controller.create(p['id'])['id'])
            self.assertIn('draft_artifacts',ctx['allowed_actions'])
            p=s.update(p['id'],p['revision'],'draft_artifacts',payload(stage))
        self.assertEqual(p['status'],'draft_ready')
        self.assertEqual(p['artifacts']['requirements'],requirements)
        self.assertEqual(p['verification']['hardware'],'not_run')
        with self.assertRaises(ValueError):s.update(p['id'],p['revision'],'execute',{})
        from unittest.mock import patch
        from embedded_agent.draft_verification import source_hash
        report={'status':'passed','source_sha256':source_hash(p['artifacts']['engineering_draft']['firmware']['files']),'hardware':'not_run'}
        with patch('embedded_agent.draft_verification.verify',return_value=report):
            p=s.update(p['id'],p['revision'],'draft_verify',{'cpu':'Cortex-M0plus'})
        p=s.update(p['id'],p['revision'],'execute',{})
        with ZipFile(io.BytesIO(s.download(p['id']))) as z:
            self.assertIn('engineering-draft/circuit/connections.svg',z.namelist())
            self.assertIn('engineering-draft/firmware/motion.c',z.namelist())
            self.assertIn('engineering-draft/interfaces/interfaces.md',z.namelist())
