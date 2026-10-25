import unittest
import test_design
from embedded_agent.control import DecisionController
from embedded_agent.autonomy import AutonomousRunner


class ResearchDispatchTests(unittest.TestCase):
    def test_saved_query_executes_without_observation_id_or_model_call(self):
        fixture=test_design.DesignTests();fixture.setUp()
        try:
            fixture.submit('design_plan',{'plan':fixture.plan()})
            control=DecisionController(fixture.service)
            run=control.create(fixture.project['id'])
            context=control.context(run['id'])
            self.assertEqual(context['design_observation_catalog']['valid_ids'],[])
            self.assertEqual(context['design_research_tasks']['pending'][0]['id'],'DOC')
            self.assertEqual(context['action_contracts']['design_research']['arguments_schema']['properties']['task_id']['enum'],['DOC'])
            class NoModel:
                def decide(self,context):raise AssertionError('No paid model call for an already-authored query')
            result=AutonomousRunner(control,NoModel()).step(run['id'])
            self.assertEqual(result['status'],'continue')
            self.assertEqual(result['context']['run']['steps'],1)
            self.assertEqual(result['context']['run'].get('auto_turns',0),0)
            self.assertEqual(result['context']['run']['observations'][-1]['status'],'executed')
            self.assertEqual(result['context']['design_research_tasks']['pending'],[])
            self.assertTrue(result['context']['design_observation_catalog']['valid_ids'])
        finally:fixture.tearDown()


if __name__=='__main__':unittest.main()
