from copy import deepcopy
import unittest
from embedded_agent.model_context import prepare, encoded
from embedded_agent.autonomy import ModelDecider


class ContextTests(unittest.TestCase):
    def sample(self):
        observations = [{'digest': str(i), 'status': 'executed', 'action': 'search_documents',
                         'tool_result': {'text': 'original text' * 2000}} for i in range(10)]
        return {'project': {'id': 'fixture', 'description': '用户要求', 'status': 'build_failed',
                            'events': [{'action': 'old', 'data': 'event' * 10000} for _ in range(8)],
                            'artifacts': {'requirements': {'constraints': ['10元预算', '电池供电'], 'acceptance': ['验收']},
                                          'design_loop': {'rounds': [{'number': 1, 'plan': {'objectives': ['续航48小时']}, 'status': 'failed', 'gaps': ['不满足']},
                                                                     {'number': 2, 'plan': {'objectives': ['续航48小时']}, 'status': 'researching'}]}}},
                'run': {'observations': observations, 'receipts': {str(i): o for i, o in enumerate(observations)},
                        'task_plan': {'goal': 'build'}, 'user_messages': [{'content': '不允许删除功能'}]},
                'allowed_actions': ['read_keil_source', 'keil_edit'], 'authority': '用户确认',
                'action_contracts': {'keil_edit': {'required': ['sha256']}}}

    def test_compact_preserves_decisive_state_and_original(self):
        original = self.sample(); saved = deepcopy(original)
        result = prepare(original)
        self.assertEqual(original, saved)
        self.assertLess(len(encoded(result)), len(encoded(original)) // 3)
        self.assertEqual(result['project']['artifacts']['requirements'], original['project']['artifacts']['requirements'])
        self.assertEqual(result['run']['user_messages'], original['run']['user_messages'])
        self.assertEqual(result['run']['observations'], original['run']['observations'][-3:])
        self.assertEqual(set(result['run']['receipts']), set(original['run']['receipts']))
        self.assertEqual(result['project']['artifacts']['design_loop']['rounds'], original['project']['artifacts']['design_loop']['rounds'][-1:])
        self.assertEqual(result['project']['artifacts']['design_loop']['prior_rounds'][0]['objectives'], ['续航48小时'])
        self.assertEqual(result['authority'], original['authority'])
        self.assertEqual(result['action_contracts'], original['action_contracts'])

    def test_human_guides_omitted_but_contract_and_evidence_kept(self):
        ctx=self.sample();ctx['engineering_guides']={'design':'操作指南'*5000}
        prepared=prepare(ctx)
        self.assertNotIn('engineering_guides',prepared)
        self.assertIn('design',prepared['guide_index'])
        self.assertEqual(prepared['action_contracts'],ctx['action_contracts'])
        self.assertIn('engineering_guides',ctx)

    def test_repair_view_keeps_actual_tests_and_failure_without_research_history(self):
        ctx=self.sample();ctx['project']['status']='draft_verification_failed'
        a=ctx['project']['artifacts'];a['engineering_draft']={'firmware':{'files':{'a.c':'int a;','test_a.c':'assert(x);','README.md':'old'}}}
        a['draft_verification']={'host_tests':{'log':'Assertion failed: x, file test_a.c, line 1'}}
        before=deepcopy(ctx);out=prepare(ctx)
        self.assertEqual(ctx,before)
        self.assertNotIn('design_loop',out['project']['artifacts'])
        self.assertEqual(out['project']['artifacts']['engineering_draft']['firmware']['files']['test_a.c'],'assert(x);')
        self.assertEqual(out['debugging_focus']['line'],1)

    def test_decider_uses_prepared_view_without_extra_model_calls(self):
        class Fake:
            calls = 0
            def generate(self, **kwargs):
                self.calls += 1
                self.context = kwargs['context']
                return {'kind': 'pause', 'reason': 'test'}
        fake = Fake()
        ModelDecider(fake).decide(self.sample())
        self.assertEqual(fake.calls, 1)
        self.assertIn('context_window', fake.context)

    def test_repeated_round_snapshots_referenced_not_resent(self):
        context = self.sample()
        snapshot = {'round': 2, 'status': 'researching', 'research_results': ['duplicate' * 10000]}
        context['run']['observations'] = [dict(action='design_evaluate', status='executed', tool_result=deepcopy(snapshot)) for _ in range(3)]
        result = prepare(context)
        for item in result['run']['observations']:
            self.assertEqual(item['tool_result']['current_round_ref'], 'project.artifacts.design_loop.rounds[-1]')
            self.assertNotIn('research_results', item['tool_result'])
        # Actual errors and source reads remain intact, not mistaken for snapshots.
        context['run']['observations'][0]['status'] = 'rejected'
        result = prepare(context)
        self.assertEqual(result['run']['observations'][0]['tool_result'], snapshot)


if __name__ == '__main__': unittest.main()
