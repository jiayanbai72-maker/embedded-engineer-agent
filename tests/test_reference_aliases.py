from copy import deepcopy
import unittest
import test_design
from embedded_agent.control import DecisionController
from embedded_agent.contracts import CONTRACTS, validate_shape
from embedded_agent.design import observation_ids


class ReferenceAliasTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_design.DesignTests(); self.fixture.setUp()
        self.control = DecisionController(self.fixture.service)
        self.run = self.control.create(self.fixture.project['id'])
        self.act('design_plan', {'plan': self.fixture.plan()})
        self.act('design_research', {'task_id':'DOC'})
        self.act('design_evaluate', {})

    def tearDown(self): self.fixture.tearDown()

    def act(self, action, args):
        run = self.control.load(self.run['id'])
        self.control.submit(run['id'], run['revision'], {'id':'test-'+str(run['steps']), 'action':action,
            'arguments':args, 'rationale':'fixture authored', 'expected':'real receipt', 'source':'test_fixture',
            'project_revision':run['project_revision']})
        return self.control.advance(run['id'])

    def test_expands_only_real_current_round_receipt_and_exposes_enum(self):
        run = self.control.load(self.run['id']); receipt = run['observations'][-1]
        context = self.control.context(run['id']); valid = context['design_observation_catalog']['valid_ids']
        enum = context['action_contracts']['design_plan']['arguments_schema']['properties']['plan']['properties']['response_to']['items']['enum']
        self.assertEqual(valid, enum)
        original = {'plan':{'response_to':[receipt['digest']], 'changes':[{'observation_ids':[receipt['digest']]}]}}
        saved = deepcopy(original)
        result, audit = self.control.normalize_design_references(run['id'], original)
        self.assertEqual(set(result['plan']['response_to']), set(valid))
        self.assertTrue(audit)
        self.assertEqual(original, saved)
        unknown, audit = self.control.normalize_design_references(run['id'], {'plan':{'response_to':['made-up-id']}})
        self.assertEqual(unknown['plan']['response_to'], ['made-up-id'])
        self.assertFalse(audit)

    def test_old_round_alias_is_not_reused(self):
        run = self.control.load(self.run['id']); receipt = run['observations'][-1]
        # Simulate a different round only in the receipt; no real state is changed.
        key = next(k for k,v in run['receipts'].items() if v['digest']==receipt['digest'])
        run['receipts'][key]['tool_result']['round'] = 0
        self.control.save(run)
        result, audit = self.control.normalize_design_references(run['id'], {'plan':{'response_to':[receipt['digest']]}})
        self.assertEqual(result['plan']['response_to'], [receipt['digest']])
        self.assertFalse(audit)


if __name__=='__main__': unittest.main()
