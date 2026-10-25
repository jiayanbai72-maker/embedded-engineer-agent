from copy import deepcopy
import unittest
import test_control
from embedded_agent.autonomy import AutonomousRunner
from embedded_agent.decision_protocol import normalize, frame
from embedded_agent.planning import validate


class ProtocolTests(unittest.TestCase):
    def context(self):
        return {'allowed_actions':['build'], 'task_progress':{'tasks':[{'id':'BUILD','action':'build','status':'ready','title':'编译'}]}}

    def test_simple_action_gets_record_fields_and_unique_task(self):
        result=normalize({'action':'build','arguments':{},'reason':'验证当前源码'},self.context())
        self.assertEqual(result['task_id'],'BUILD')
        self.assertIn('expected',result['metadata_defaults'])
        self.assertEqual(result['rationale'],'验证当前源码')

    def test_record_rationale_reused_without_changing_source(self):
        ctx={'allowed_actions':['draft_edit'],'action_contracts':{'draft_edit':{'arguments_schema':{'required':['changes','rationale']}}}}
        args={'changes':[{'file':'a.c','sha256':'fixture','content':'int a;'}]}
        answer=normalize({'action':'draft_edit','arguments':args,'reason':'模型提供的修复依据'},ctx)
        self.assertEqual(answer['arguments']['rationale'],'模型提供的修复依据')
        self.assertEqual(answer['arguments']['changes'],args['changes'])
        self.assertNotIn('rationale',args)

    def test_ambiguous_task_and_unauthorized_action_still_rejected(self):
        ctx=self.context();ctx['task_progress']['tasks'].append(dict(ctx['task_progress']['tasks'][0],id='OTHER'))
        with self.assertRaisesRegex(ValueError,'多个同类'):normalize({'action':'build','arguments':{},'reason':'x'},ctx)
        with self.assertRaises(ValueError):normalize({'action':'confirm','arguments':{},'reason':'x'},ctx)

    def test_short_plan_compiles_to_real_success_conditions(self):
        answer={'kind':'plan','plan':{'goal':'离线验证','reason':'先构建再测','tasks':[{'action':'build','title':'构建'},{'action':'test','title':'测试'}]}}
        original=deepcopy(answer);result=normalize(answer,self.context())
        validate(result['plan'],{'build','test'})
        self.assertEqual(result['plan']['tasks'][1]['depends_on'],['task_1'])
        self.assertEqual(result['plan']['tasks'][0]['completion']['tool_result.status'],'passed')
        self.assertEqual(answer,original)

    def test_pause_reply_preserves_project_and_completed_work(self):
        fixture=test_control.ControlTests();fixture.setUp()
        try:
            run=fixture.prepared()
            before=deepcopy(fixture.service.get(run['project_id']))
            class Provider:
                calls=0
                def decide(self,context):
                    self.calls+=1
                    return {'kind':'pause','reason':'需要用户选择设计范围'}
            provider=Provider();runner=AutonomousRunner(fixture.control,provider)
            paused=runner.step(run['id'])['context']['run']
            runner.step(run['id'])
            self.assertEqual(provider.calls,1)
            result=fixture.control.reply(run['id'],paused['revision'],'保留目标，按标注假设继续')['run']
            self.assertEqual(fixture.service.get(run['project_id']),before)
            self.assertEqual(result['receipts'],paused['receipts'])
            self.assertEqual(result['steps'],paused['steps'])
            self.assertEqual(result['user_messages'][-1]['question'],'需要用户选择设计范围')
            self.assertNotIn('pause_question',result)
            self.assertEqual(result['status'],'awaiting_decision')
            with self.assertRaises(ValueError):fixture.control.reply(run['id'],paused['revision'],'重复提交')
        finally:fixture.tearDown()

    def test_repeated_read_stops_without_reexecuting_tool(self):
        fixture=test_control.ControlTests();fixture.setUp()
        try:
            run=fixture.prepared()
            class Provider:
                def decide(self,context):return {'action':'search_documents','arguments':{'query':'fixture query'},'reason':'找资料'}
            # No library is configured in this fixture: install a deterministic
            # read tool response. This is explicitly not a model/network test.
            from unittest.mock import patch
            runner=AutonomousRunner(fixture.control,Provider())
            with patch.object(fixture.service.app.tools,'execute',return_value={'status':'passed','matches':[]}) as tool:
                first=runner.step(run['id']);second=runner.step(run['id'])
                self.assertEqual(first['status'],'continue')
                self.assertEqual(second['reason_code'],'repeated_work')
                self.assertEqual(tool.call_count,1)
                self.assertEqual(second['context']['run']['steps'],1)
        finally:fixture.tearDown()


if __name__=='__main__':unittest.main()
