from copy import deepcopy
import unittest
import test_design
from embedded_agent.autonomy import AutonomousRunner
from embedded_agent.control import DecisionController


class ValidationRepairTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_design.DesignTests()
        self.fixture.setUp()
        project = self.fixture.project
        candidate = project['artifacts']['comparison']['candidates'][0]['id']
        self.fixture.project = self.fixture.service.update(project['id'], project['revision'], 'select', {'candidate_id': candidate})
        self.control = DecisionController(self.fixture.service)
        self.run = self.control.create(self.fixture.project['id'])

    def tearDown(self): self.fixture.tearDown()

    def provider(self, bad, good):
        class Provider:
            calls = 0
            contexts = []
            def decide(self, context):
                self.contexts.append(deepcopy(context)); self.calls += 1
                return {'kind': 'decision', 'action': 'design_plan', 'arguments': {'plan': bad if self.calls == 1 else good},
                        'rationale': 'fixture follows actual validation feedback', 'expected': 'persist validated plan'}
        return Provider()

    def test_service_error_visible_and_model_corrects_next_step(self):
        good = self.fixture.plan(); bad = deepcopy(good)
        bad['objectives'][0].update(kind='budget', fixed_inputs={})
        provider = self.provider(bad, good)
        runner = AutonomousRunner(self.control, provider)
        first = runner.step(self.run['id'])
        self.assertEqual(first['status'], 'continue')
        receipt = first['context']['run']['observations'][-1]
        self.assertEqual(receipt['status'], 'rejected')
        self.assertIn('objectives[0].fixed_inputs', receipt['message'])
        self.assertEqual(receipt['tool_result']['attempted_arguments']['plan'], bad)
        self.assertEqual(first['context']['project']['revision'], self.fixture.project['revision'])
        second = runner.step(self.run['id'])
        self.assertEqual(second['context']['run']['observations'][-1]['status'], 'executed')
        self.assertEqual(provider.contexts[1]['run']['auto_feedback']['action'], 'design_plan')
        self.assertNotIn('auto_feedback', second['context']['run'])
        self.assertEqual(second['context']['project']['artifacts']['design_loop']['rounds'][-1]['plan'], good)

    def test_shape_error_contains_field_path_and_attempt_for_repair(self):
        good = self.fixture.plan(); bad = deepcopy(good)
        del bad['candidates'][0]['proposal']
        provider = self.provider(bad, good)
        runner = AutonomousRunner(self.control, provider)
        first = runner.step(self.run['id'])
        self.assertIn('arguments.plan.candidates[0].proposal', first['context']['run']['auto_feedback']['message'])
        self.assertEqual(first['context']['run']['steps'], 0)
        second = runner.step(self.run['id'])
        self.assertEqual(second['context']['run']['observations'][-1]['status'], 'executed')

    def test_three_failures_pause_without_fourth_call(self):
        bad = self.fixture.plan(); bad['objectives'][0].update(kind='budget', fixed_inputs={})
        provider = self.provider(bad, bad)
        runner = AutonomousRunner(self.control, provider)
        for _ in range(3): result = runner.step(self.run['id'])
        self.assertEqual(result['status'], 'paused')
        self.assertEqual(provider.calls, 3)
        runner.step(self.run['id'])
        self.assertEqual(provider.calls, 3)
        self.assertNotIn('design_loop', self.fixture.service.get(self.fixture.project['id'])['artifacts'])


if __name__ == '__main__': unittest.main()
