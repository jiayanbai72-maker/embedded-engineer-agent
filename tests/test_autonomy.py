import unittest
import test_control
from embedded_agent.autonomy import AutonomousRunner


class Provider:
    def __init__(self, answer): self.answer, self.calls = answer, 0
    def decide(self, context):
        self.calls += 1
        return self.answer


class AutonomyTests(unittest.TestCase):
    setUp = test_control.ControlTests.setUp
    tearDown = test_control.ControlTests.tearDown
    prepared = test_control.ControlTests.prepared
    code = test_control.ControlTests.code

    def test_unconfigured_does_not_execute(self):
        run = self.prepared()
        result = AutonomousRunner(self.control).step(run['id'])
        self.assertEqual(result['status'], 'model_not_connected')
        self.assertEqual(self.control.load(run['id'])['steps'], 0)

    def test_decision_executes_and_observes(self):
        run = self.prepared()
        provider = Provider({'kind': 'decision', 'action': 'implementation', 'arguments': self.code(True),
                             'rationale': '先实现行为原型', 'expected': '获得可构建源码'})
        result = AutonomousRunner(self.control, provider).step(run['id'])
        self.assertEqual(result['status'], 'continue')
        self.assertEqual(result['context']['project']['status'], 'ready_build')
        self.assertEqual(result['context']['run']['steps'], 1)

    def test_no_confirmation_bypass_and_error_budget(self):
        run = self.prepared()
        provider = Provider({'kind': 'decision', 'action': 'confirm', 'arguments': {'confirmed': True}})
        runner = AutonomousRunner(self.control, provider)
        for expected in ('continue', 'continue', 'paused', 'paused'):
            self.assertEqual(runner.step(run['id'])['status'], expected)
        self.assertEqual(provider.calls, 3)
        self.assertEqual(self.control.load(run['id'])['steps'], 0)

    def test_pause_is_not_fake_completion(self):
        run = self.prepared()
        provider = Provider({'kind': 'pause', 'reason': '需用户确认交付范围'})
        result = AutonomousRunner(self.control, provider).step(run['id'])
        self.assertEqual(result['status'], 'paused')
        self.assertEqual(result['context']['run']['status'], 'awaiting_decision')

    def test_user_confirmation_stops_before_model_call(self):
        run = self.prepared()
        project = self.service.app.store.load(run['project_id'])
        project.status = 'awaiting_selection'
        self.service.app.store.save(project)
        provider = Provider({'kind': 'decision', 'action': 'select', 'arguments': {}})
        result = AutonomousRunner(self.control, provider).step(run['id'])
        self.assertEqual(result['status'], 'paused')
        self.assertEqual(provider.calls, 0)


if __name__ == '__main__': unittest.main()
