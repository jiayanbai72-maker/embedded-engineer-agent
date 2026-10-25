import unittest
import test_control
from embedded_agent.autonomy import AutonomousRunner


class CompletedPlanTests(unittest.TestCase):
    def setUp(self):
        self.fixture=test_control.ControlTests(); self.fixture.setUp()
        self.run=self.fixture.prepared(); self.control=self.fixture.control
        self.control.plan(self.run['id'],self.run['revision'],{'goal':'fixture build','rationale':'fixture','source':'fixture',
            'tasks':[{'id':'CODE','title':'implement','action':'implementation','depends_on':[],'completion':{'status':'executed'}},
                     {'id':'BUILD','title':'compile','action':'build','depends_on':['CODE'],'completion':{'status':'executed'}}]})

    def tearDown(self):self.fixture.tearDown()

    def act(self, action, task, args):
        run=self.control.load(self.run['id'])
        decision=self.fixture.decision(run,action,args);decision['task_id']=task
        self.control.submit(run['id'],run['revision'],decision)
        return self.control.advance(run['id'])

    def test_only_ready_actions_visible_and_completed_plan_closes_without_model(self):
        context=self.control.context(self.run['id'])
        self.assertEqual(set(context['allowed_actions']),{'implementation','ask'})
        self.assertFalse(self.control.close_completed_plan(self.run['id']))
        self.act('implementation','CODE',self.fixture.code(True))
        context=self.control.context(self.run['id'])
        self.assertEqual(set(context['allowed_actions']),{'build','ask'})
        self.act('build','BUILD',{})
        before=self.fixture.service.get(self.run['project_id'])
        run=self.control.load(self.run['id']);run['auto_errors']=3
        run['auto_feedback']={'message':'决策必须关联当前可执行任务且动作一致'};self.control.save(run)
        class Provider:
            def decide(self,context):raise AssertionError('No paid model needed to close completed plan')
        result=AutonomousRunner(self.control,Provider()).step(run['id'])
        self.assertEqual(result['status'],'continue')
        updated=result['context']['run']
        self.assertNotIn('task_plan',updated)
        self.assertEqual(updated['completed_plan']['completed'],2)
        self.assertEqual(updated['auto_errors'],0)
        self.assertEqual(result['context']['project'],before)
        self.assertEqual(len(updated['plan_history']),1)
        self.assertFalse(self.control.close_completed_plan(run['id']))


if __name__=='__main__':unittest.main()
