import unittest
import test_control
from embedded_agent.contracts import CONTRACTS, validate_shape
from embedded_agent.control import OPERATIONS, READ_OPERATIONS, DecisionController


class ContractTests(unittest.TestCase):
    setUp = test_control.ControlTests.setUp
    tearDown = test_control.ControlTests.tearDown
    prepared = test_control.ControlTests.prepared
    decision = test_control.ControlTests.decision
    act = test_control.ControlTests.act

    def test_all_actions_described_and_types_validated(self):
        self.assertEqual(set(CONTRACTS), OPERATIONS | set(READ_OPERATIONS) | {'ask', 'finish'})
        with self.assertRaisesRegex(ValueError, 'arguments.files'):
            validate_shape(CONTRACTS['implementation'], {'rationale': '实现'})
        with self.assertRaises(ValueError):
            validate_shape(CONTRACTS['read_document_page'], {'document_id': 'DOC-1', 'page': True})
        with self.assertRaises(ValueError):
            validate_shape(CONTRACTS['firmware_implementation'], {'files': {'main.c': 'int x;'}, 'rationale': '演练', 'profile': {'mode': 'real_board'}})

    def test_reply_resumes_persistently_without_self_confirmation(self):
        run = self.prepared()
        run = self.act(run, 'ask', {'question': '希望优先验证哪项行为？'})
        before = self.service.get(run['project_id'])
        c = self.control.reply(run['id'], run['revision'], '优先验证按键消抖')
        self.assertEqual(c['run']['status'], 'awaiting_decision')
        self.assertEqual(c['project'], before)
        restored = DecisionController(self.service).context(run['id'])
        self.assertEqual(restored['run']['user_messages'][-1]['content'], '优先验证按键消抖')
        with self.assertRaises(ValueError):
            self.control.reply(run['id'], run['revision'], '重复回答')
        self.assertIn('implementation', c['action_contracts'])

    def test_reply_syncs_supplement_without_mutating_project(self):
        run = self.prepared()
        run = self.act(run, 'ask', {'question': '补充信息？'})
        self.service.update(run['project_id'], run['project_revision'], 'supplement', {'message': '改变需求'})
        before=self.service.get(run['project_id'])
        result=self.control.reply(run['id'], run['revision'], '补充后的回答')
        self.assertEqual(result['project'],before)
        self.assertEqual(result['run']['project_revision'],before['revision'])
        self.assertEqual(result['run']['user_messages'][-1]['content'],'补充后的回答')
        with self.assertRaises(ValueError):
            self.control.reply(run['id'],run['revision'],'旧运行版本重复提交')


if __name__ == '__main__': unittest.main()
