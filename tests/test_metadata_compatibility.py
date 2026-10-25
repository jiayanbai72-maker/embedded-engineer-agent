import unittest
import test_control
from embedded_agent.autonomy import AutonomousRunner


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_control.ControlTests(); self.fixture.setUp()
        self.run = self.fixture.prepared(); self.control = self.fixture.control

    def tearDown(self): self.fixture.tearDown()

    def test_missing_outer_metadata_does_not_cost_another_model_call(self):
        args = self.fixture.code(True)
        class Provider:
            calls = 0
            def decide(self, context):
                self.calls += 1
                return {'kind': 'decision', 'action': 'implementation', 'arguments': args}
        provider = Provider()
        result = AutonomousRunner(self.control, provider).step(self.run['id'])
        self.assertEqual(result['context']['project']['status'], 'ready_build')
        self.assertEqual(result['context']['run']['observations'][-1]['status'], 'executed')
        self.assertEqual(provider.calls, 1)
        self.assertEqual(result['context']['run'].get('auto_errors'), 0)

    def test_known_old_metadata_failure_can_recover_once(self):
        run = self.control.load(self.run['id']); run['auto_errors'] = 3
        run['auto_feedback'] = {'status': 'invalid_decision', 'message': '决策缺少依据、预期、来源或参数', 'attempted_arguments': {'rationale': 'original model rationale'}}
        self.control.save(run)
        class Provider:
            def decide(self, context): raise AssertionError('No model call during recovery')
        runner = AutonomousRunner(self.control, Provider())
        self.assertEqual(runner.step(run['id'])['status'], 'continue')
        recovered = self.control.load(run['id'])
        self.assertEqual(recovered['auto_errors'], 0)
        recovered['auto_errors'] = 3; self.control.save(recovered)
        self.assertEqual(runner.step(run['id'])['status'], 'paused')


if __name__ == '__main__': unittest.main()
