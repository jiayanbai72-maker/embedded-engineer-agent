import unittest
import test_control
from embedded_agent.planning import validate
from embedded_agent.control import DecisionController


class PlanningTests(unittest.TestCase):
    setUp = test_control.ControlTests.setUp
    tearDown = test_control.ControlTests.tearDown
    prepared = test_control.ControlTests.prepared
    decision = test_control.ControlTests.decision
    code = test_control.ControlTests.code
    def proposal(self):
        return {'goal': '通过真实主机测试后交付', 'rationale': '由代码、构建到验证，禁止跳过依赖', 'source': 'test_analyst', 'tasks': [
            {'id': 'code', 'title': '提交实现', 'action': 'implementation', 'depends_on': [], 'completion': {'status': 'executed', 'project_status': 'ready_build'}},
            {'id': 'build', 'title': '编译检查', 'action': 'build', 'depends_on': ['code'], 'completion': {'status': 'executed', 'tool_result.status': 'passed'}},
            {'id': 'test', 'title': '边界测试', 'action': 'test', 'depends_on': ['build'], 'completion': {'status': 'executed', 'project_status': 'ready_delivery'}}]}

    def task_act(self, run, task, action, args=None):
        d = dict(self.decision(run, action, args), task_id=task)
        self.control.submit(run['id'], run['revision'], d)
        return self.control.tick(run['id'])

    def test_dependency_failure_replan_and_restart(self):
        run = self.prepared()
        c = self.control.plan(run['id'], run['revision'], self.proposal())
        run = c['run']
        with self.assertRaises(ValueError):
            self.task_act(run, 'test', 'test')
        run = self.task_act(run, 'code', 'implementation', self.code())
        # A fresh controller reconstructs progress from persisted receipts.
        self.control = DecisionController(self.service)
        self.assertEqual(self.control.context(run['id'])['task_progress']['completed'], 1)
        run = self.task_act(run, 'build', 'build')
        run = self.task_act(run, 'test', 'test')
        c = self.control.context(run['id'])
        self.assertEqual(c['task_progress']['tasks'][-1]['status'], 'needs_review')
        self.assertEqual(c['task_progress']['completed'], 2)
        p = self.proposal()
        with self.assertRaises(ValueError):
            self.control.plan(run['id'], run['revision'], p)
        p['response_to'] = [list(run['receipts'])[-1]]
        p['rationale'] = '依据失败测试，重新修复实现并验证'
        c = self.control.plan(run['id'], run['revision'], p)
        self.assertEqual(c['task_progress']['version'], 2)
        self.assertEqual(c['task_progress']['completed'], 0)

    def test_cycle_and_unimplemented_capability(self):
        p = self.proposal()
        p['tasks'][0]['depends_on'] = ['test']
        with self.assertRaises(ValueError): validate(p, {'implementation', 'build', 'test'})
        p = self.proposal(); p['tasks'][0]['action'] = 'flash_hardware'
        with self.assertRaises(ValueError): validate(p, {'implementation', 'build', 'test'})

    def test_external_change_invalidates_plan(self):
        run = self.prepared()
        run = self.control.plan(run['id'], run['revision'], self.proposal())['run']
        self.service.update(run['project_id'], run['project_revision'], 'supplement', {'message': '新增低功耗要求'})
        self.assertEqual(self.control.context(run['id'])['task_progress']['tasks'][0]['status'], 'stale')
        run = self.control.refresh(run['id'], run['revision'])
        self.assertNotIn('task_plan', run)
        c = self.control.plan(run['id'], run['revision'], self.proposal())
        self.assertEqual(c['task_progress']['version'], 2)


if __name__ == '__main__': unittest.main()
