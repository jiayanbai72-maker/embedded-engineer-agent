import importlib.util
import json
from unittest.mock import patch
import unittest
import threading
import urllib.request
import test_architecture
from embedded_agent.control import DecisionController
from embedded_agent.service import EngineeringService
from embedded_agent.server import make_server


def sample_module():
    spec = importlib.util.spec_from_file_location('control_sample', test_architecture.ROOT / 'examples/run_full_flow.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ControlTests(unittest.TestCase):
    setUp = test_architecture.ArchitectureTests.setUp
    tearDown = test_architecture.ArchitectureTests.tearDown

    def test_supplement_releases_stale_wait_without_model_call(self):
        from embedded_agent.autonomy import AutonomousRunner
        run=self.prepared()
        run.update(status='waiting_input',pause_question='old question')
        self.control.save(run)
        self.service.update(self.project['id'],self.project['revision'],'supplement',{'message':'蓝牙遥控，每腿一个关节，其余由Agent提出方案'})
        class Provider:
            def decide(self,context):raise AssertionError('Must not call model while synchronizing')
        result=AutonomousRunner(self.control,Provider()).step(run['id'])
        self.assertEqual(result['status'],'continue')
        current=self.control.load(run['id'])
        self.assertEqual(current['status'],'awaiting_decision')
        self.assertNotIn('pause_question',current)
        self.assertEqual(current['project_revision'],self.service.get(self.project['id'])['revision'])

    def test_reply_syncs_changed_requirements_once(self):
        run=self.prepared();run.update(status='waiting_input',pause_question='old question');self.control.save(run)
        self.service.update(self.project['id'],self.project['revision'],'supplement',{'message':'蓝牙遥控'})
        result=self.control.reply(run['id'],run['revision'],'每腿一个关节，型号由Agent提出')
        self.assertEqual(result['run']['status'],'awaiting_decision')
        self.assertEqual(len(result['run']['user_messages']),1)
        self.assertEqual(result['run']['project_revision'],result['project']['revision'])

    def prepared(self, repairs=3, steps=20):
        self.sample = sample_module()
        self.service = EngineeringService(self.root)
        p = self.service.create('单输入按键原型演练')
        p = self.service.update(p['id'], p['revision'], 'analysis', self.sample.authored_analysis())
        p = self.service.update(p['id'], p['revision'], 'confirm', {'confirmed': True})
        self.project = self.service.update(p['id'], p['revision'], 'select', {'candidate_id': 'PLAN-1'})
        self.control = DecisionController(self.service)
        return self.control.create(p['id'], max_steps=steps, max_repairs=repairs)

    def decision(self, run, action, args=None):
        return {'id': 'DEC-' + str(run['steps']), 'project_revision': run['project_revision'],
                'action': action, 'arguments': args or {}, 'rationale': '测试分析者根据当前上下文决定动作',
                'expected': '保存真实结果并用于下一轮判断', 'source': 'contract_test_fixture'}

    def act(self, run, action, args=None):
        self.control.submit(run['id'], run['revision'], self.decision(run, action, args))
        return self.control.tick(run['id'])

    def code(self, fixed=False):
        source = self.sample.SOURCE
        if fixed: source = source.replace('> self.debounce_ms', '>= self.debounce_ms')
        return {'files': {'button.py': source, 'test_button.py': self.sample.TESTS}, 'rationale': '边界错误故障演练' if not fixed else '根据20ms失败修复比较条件'}

    def test_feedback_branches_and_completion(self):
        run = self.prepared()
        run = self.act(run, 'implementation', self.code())
        run = self.act(run, 'build')
        run = self.act(run, 'test')
        self.assertEqual(run['observations'][-1]['project_status'], 'test_failed')
        self.assertIn('test_exact_boundary', run['observations'][-1]['tool_result']['log'])
        run = self.act(run, 'implementation', self.code(True))
        self.assertEqual(run['repairs'], 1)
        run = self.act(run, 'build')
        run = self.act(run, 'test')
        run = self.act(run, 'execute')
        run = self.act(run, 'finish')
        self.assertEqual(run['status'], 'complete')
        self.assertEqual(self.service.get(run['project_id'])['verification']['hardware'], 'not_run')

    def test_no_provider_and_waiting_input(self):
        run = self.prepared()
        self.assertEqual(self.control.tick(run['id'])['revision'], 0)
        run = self.act(run, 'ask', {'question': '需要多少毫秒去抖？'})
        self.assertEqual(run['status'], 'waiting_input')
        self.assertEqual(self.control.tick(run['id'])['revision'], run['revision'])
        project = self.service.get(run['project_id'])
        self.service.update(project['id'], project['revision'], 'supplement', {'message': '改为30毫秒'})
        run = self.control.refresh(run['id'], run['revision'])
        self.assertEqual(self.control.context(run['id'])['project']['status'], 'awaiting_analysis')

    def test_duplicate_does_not_reexecute(self):
        run = self.prepared()
        decision = self.decision(run, 'implementation', self.code(True))
        self.control.submit(run['id'], run['revision'], decision)
        executed = self.control.advance(run['id'])
        with patch.object(self.service, 'update', side_effect=AssertionError('must not run')):
            self.assertEqual(self.control.submit(run['id'], 0, decision), executed)
            self.assertEqual(self.control.tick(run['id']), executed)
        decision['rationale'] = 'changed'
        with self.assertRaises(ValueError): self.control.submit(run['id'], executed['revision'], decision)

    def test_permission_and_early_finish_rejected(self):
        run = self.prepared()
        for action in ('confirm', 'select', 'shell', 'flash', 'finish', 'test'):
            with self.assertRaises(ValueError): self.control.submit(run['id'], run['revision'], self.decision(run, action))

    def test_stale_pending_is_not_executed(self):
        run = self.prepared()
        self.control.submit(run['id'], run['revision'], self.decision(run, 'implementation', self.code()))
        p = self.service.get(run['project_id'])
        self.service.update(p['id'], p['revision'], 'supplement', {'message': '改变目标'})
        run = self.control.advance(run['id'])
        self.assertEqual(run['observations'][-1]['status'], 'stale')
        self.assertNotIn('implementation', self.service.get(run['project_id'])['artifacts'])

    def test_repair_and_step_budgets(self):
        run = self.prepared(repairs=0)
        run = self.act(run, 'implementation', self.code())
        run = self.act(run, 'build')
        run = self.act(run, 'test')
        with self.assertRaises(ValueError): self.control.submit(run['id'], run['revision'], self.decision(run, 'implementation', self.code(True)))
        self.assertEqual(self.control.load(run['id'])['status'], 'repair_limit')
        run = self.prepared(steps=1)
        run = self.act(run, 'implementation', self.code(True))
        with self.assertRaises(ValueError): self.control.submit(run['id'], run['revision'], self.decision(run, 'build'))
        self.assertEqual(self.control.load(run['id'])['status'], 'budget_exhausted')

    def test_restart_recovers_committed_action_and_uncertain_stops(self):
        run = self.prepared()
        decision = self.decision(run, 'implementation', self.code(True))
        run = self.control.submit(run['id'], run['revision'], decision)
        run['status'] = 'executing'; self.control.save(run)
        self.service.update(run['project_id'], decision['project_revision'], 'implementation', decision['arguments'])
        restarted = DecisionController(EngineeringService(self.root))
        run = restarted.advance(run['id'])
        self.assertEqual(run['observations'][-1]['status'], 'executed')
        self.assertIn('未重复执行', run['observations'][-1]['message'])
        run = restarted.submit(run['id'], run['revision'], self.decision(run, 'build'))
        run['status'] = 'executing'; restarted.save(run)
        self.assertEqual(restarted.advance(run['id'])['status'], 'interrupted_unknown')

    def test_provider_uses_observed_context(self):
        run = self.prepared()
        class Provider:
            def decide(inner, context):
                self.assertIn('implementation', context['allowed_actions'])
                self.assertEqual(context['project']['status'], 'awaiting_implementation')
                return self.decision(context['run'], 'implementation', self.code(True))
        run = self.control.tick(run['id'], Provider())
        self.assertEqual(run['observations'][-1]['project_status'], 'ready_build')

    def test_http_decision_submission_and_restart(self):
        def start():
            server = make_server(self.root, 0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            return server, thread
        server, thread = start()
        def request(path, payload=None):
            req = urllib.request.Request(f'http://127.0.0.1:{server.server_port}' + path,
                                         data=None if payload is None else json.dumps(payload).encode(),
                                         headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=5) as response:
                return json.loads(response.read())
        try:
            project = request('/projects', {'description': '需要确认部署环境'})
            run = request('/runs', {'project_id': project['id']})
            decision = self.decision(run, 'ask', {'question': '室内还是室外？'})
            request('/runs/' + run['id'] + '/decisions', {'revision': run['revision'], 'decision': decision})
            server.shutdown(); server.server_close(); thread.join()
            server, thread = start()
            run = request('/runs/' + run['id'] + '/tick', {})
            self.assertEqual(run['status'], 'waiting_input')
            context = request('/runs/' + run['id'])
            self.assertEqual(context['run']['observations'][-1]['message'], '室内还是室外？')
        finally:
            server.shutdown(); server.server_close(); thread.join()
