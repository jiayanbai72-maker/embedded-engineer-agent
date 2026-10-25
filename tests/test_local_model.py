import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from embedded_agent.local_model import Budget, BudgetModel, BudgetPaused, LocalSettings, protect


class LocalModelTests(unittest.TestCase):
    def test_helper_roles_remove_unrelated_contracts_and_measure_prefix_without_secrets(self):
        requests=[]
        body={'usage':{'prompt_tokens':1000,'completion_tokens':10},'choices':[{'finish_reason':'stop','message':{'content':'{"supported":true}'}}]}
        model=BudgetModel('deepseek-flash','fixture-secret',self.budget)
        receipts=[]
        for role in ('legacy_fixture','evidence_verifier','evidence_verifier','requirements','comparison'):
            with patch('embedded_agent.local_model.build_opener') as op:
                op.return_value.open.return_value=io.BytesIO(json.dumps(body).encode())
                model.generate(role=role,instruction='fixed',context={'source':'source-preserved','claim':'claim-preserved'})
                requests.append(json.loads(op.return_value.open.call_args.args[0].data))
                receipts.append(self.budget.receipt(model.last_call_id))
        legacy=len(json.dumps(requests[0]['messages']))
        for index in (1,3,4):
            current=requests[index]['messages']
            self.assertLess(len(json.dumps(current)),legacy//2)
            self.assertNotIn('action_contracts',json.loads(current[1]['content'])['protocol_and_contracts'])
            self.assertIn('source-preserved',json.dumps(current));self.assertIn('claim-preserved',json.dumps(current))
        self.assertFalse(receipts[1]['request_metrics']['prefix_seen_before'])
        self.assertTrue(receipts[2]['request_metrics']['prefix_seen_before'])
        self.assertEqual(Budget(self.budget.path).receipt(model.last_call_id),receipts[-1])
        self.assertNotIn('fixture-secret',json.dumps(receipts))
        self.assertNotIn('source-preserved',json.dumps(receipts))
        self.assertIsNone(receipts[1]['cache_hit_tokens'])
        groups=[g for g in self.budget.status()['usage_groups'] if g['role']=='evidence_verifier']
        self.assertEqual(len(groups),2)
        self.assertEqual(sum(g['calls'] for g in groups),2)
        self.assertTrue(all(g['cache_hit_ratio'] is None for g in groups))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.budget = Budget(self.root / 'budget.sqlite3')

    def tearDown(self): self.tmp.cleanup()

    def test_reserves_before_request_and_survives_restart(self):
        self.budget.reserve(9_999_999_999)
        model = BudgetModel('deepseek-flash', 'fixture-secret', self.budget)
        with patch('embedded_agent.local_model.build_opener') as network:
            with self.assertRaises(BudgetPaused): model.generate(role='x', instruction='json', context={})
            network.assert_not_called()
        with self.assertRaises(BudgetPaused): Budget(self.budget.path).reserve(100_000_000)

    def test_usage_cache_and_output_settled_even_invalid_json(self):
        model = BudgetModel('deepseek-flash', 'fixture-secret', self.budget)
        body = {'usage': {'prompt_tokens': 1000, 'prompt_cache_hit_tokens': 500, 'prompt_cache_miss_tokens': 500, 'completion_tokens': 100},
                'choices': [{'finish_reason': 'stop', 'message': {'content': 'not json'}}]}
        with patch('embedded_agent.local_model.build_opener') as op:
            op.return_value.open.return_value = io.BytesIO(json.dumps(body).encode())
            with self.assertRaises(ValueError): model.generate(role='x', instruction='json', context={})
            payload = json.loads(op.return_value.open.call_args.args[0].data)
            self.assertEqual(payload['max_tokens'], 393216)
        self.assertAlmostEqual(self.budget.status()['accounted_cny'], .00182)
        self.assertEqual(self.budget.status()['prompt_tokens'], 1000)
        self.assertEqual(self.budget.status()['reserved_cny'], 0)

    def test_large_context_and_output_are_not_subject_to_old_test_quotas(self):
        model=BudgetModel('deepseek-flash','fixture-secret',self.budget)
        body={'usage':{'prompt_tokens':40000,'completion_tokens':9000,'prompt_cache_hit_tokens':0,'prompt_cache_miss_tokens':40000},
              'choices':[{'finish_reason':'stop','message':{'content':'{"ok":true}'}}]}
        with patch('embedded_agent.local_model.build_opener') as op:
            op.return_value.open.return_value.__enter__.return_value.read.return_value=json.dumps(body).encode()
            self.assertTrue(model.generate(role='x',instruction='JSON',context={'text':'a'*230000})['ok'])
            request=json.loads(op.return_value.open.call_args.args[0].data)
            self.assertEqual(request['max_tokens'],393216)
        receipt=self.budget.receipt(model.last_call_id)
        self.assertEqual(receipt['completion_tokens'],9000)
        self.assertEqual(receipt['cache_miss_tokens'],40000)

    def test_output_is_bounded_by_money_not_an_independent_token_quota(self):
        self.budget.reserve(9_900_000_000)
        model=BudgetModel('deepseek-flash','fixture-secret',self.budget)
        body={'usage':{'prompt_tokens':100,'completion_tokens':10},'choices':[{'finish_reason':'stop','message':{'content':'{}'}}]}
        with patch('embedded_agent.local_model.build_opener') as op:
            op.return_value.open.return_value.__enter__.return_value.read.return_value=json.dumps(body).encode()
            model.generate(role='x',instruction='JSON',context={})
            request=json.loads(op.return_value.open.call_args.args[0].data)
            self.assertGreater(request['max_tokens'],0);self.assertLess(request['max_tokens'],393216)
        self.assertLessEqual(self.budget.status()['accounted_cny'],10)

    def test_static_prefix_and_cache_metrics(self):
        from copy import deepcopy
        model=BudgetModel('deepseek-flash','fixture-secret',self.budget)
        contexts=[{'allowed_actions':['ask'],'action_contracts':{'ask':{'enum':['R1']}}},
                  {'allowed_actions':['draft_artifacts'],'action_contracts':{'ask':{'enum':['R2']}}}]
        requests=[]
        for context in contexts:
            body={'usage':{'prompt_tokens':1000,'completion_tokens':10,'prompt_cache_hit_tokens':600,'prompt_cache_miss_tokens':400},
                  'choices':[{'finish_reason':'stop','message':{'content':'{"kind":"pause","reason":"fixture"}'}}]}
            original=deepcopy(context)
            with patch('embedded_agent.local_model.build_opener') as op:
                op.return_value.open.return_value.__enter__.return_value.read.return_value=json.dumps(body).encode()
                model.generate(role='x',instruction='fixed',context=context)
                requests.append(json.loads(op.return_value.open.call_args.args[0].data))
            self.assertEqual(context,original)
        self.assertEqual(requests[0]['messages'][:2],requests[1]['messages'][:2])
        self.assertNotEqual(requests[0]['messages'][-1],requests[1]['messages'][-1])
        status=self.budget.status()
        self.assertEqual(status['cache_hit_tokens'],1200)
        self.assertEqual(status['cache_miss_tokens'],800)
        self.assertEqual(status['cache_measured_calls'],2)
        self.assertEqual(status['cache_hit_ratio'],0.6)

    def test_unknown_usage_and_timeout_pause_no_retry(self):
        model = BudgetModel('deepseek-flash', 'fixture-secret', self.budget)
        with patch('embedded_agent.local_model.build_opener') as op:
            op.return_value.open.side_effect = TimeoutError()
            with self.assertRaises(BudgetPaused): model.generate(role='x', instruction='json', context={})
        self.assertTrue(self.budget.status()['uncertain'])
        self.assertGreater(self.budget.status()['reserved_cny'], 0)
        with self.assertRaises(BudgetPaused): self.budget.reserve(1)

    def test_focused_repair_omits_unrelated_contracts_and_keeps_budget(self):
        model = BudgetModel('deepseek-flash', 'fixture-secret', self.budget)
        body = {'usage': {'prompt_tokens': 1000, 'completion_tokens': 10},
                'choices': [{'finish_reason': 'stop', 'message': {'content': '{"patches":[]}'}}]}
        with patch('embedded_agent.local_model.build_opener') as op:
            op.return_value.open.return_value = io.BytesIO(json.dumps(body).encode())
            model.generate(role='focused_repair', instruction='repair', context={'files': {'a.c': 'fixture'}})
            payload = json.loads(op.return_value.open.call_args.args[0].data)
        prefix = json.loads(payload['messages'][1]['content'])['protocol_and_contracts']
        self.assertIn('repair_contract', prefix)
        self.assertNotIn('action_contracts', prefix)
        self.assertIn('fixture', json.dumps(payload['messages'],ensure_ascii=False))
        self.assertEqual(self.budget.status()['completed_calls'], 1)
        self.assertGreater(self.budget.status()['accounted_cny'], 0)

    def test_atomic_shared_budget_and_shanghai_rollover(self):
        def reserve(_):
            try: self.budget.reserve(6_000_000_000); return True
            except BudgetPaused: return False
        with patch('embedded_agent.local_model.today', return_value='2026-10-17'):
            with ThreadPoolExecutor(2) as pool: self.assertEqual(sum(pool.map(reserve, range(2))), 1)
            with self.budget.db() as db: db.execute("UPDATE calls SET state='settled'")
        with patch('embedded_agent.local_model.today', return_value='2026-10-18'):
            self.assertEqual(self.budget.status()['remaining_cny'], 10)
            self.budget.reserve(6_000_000_000)

    def test_missing_usage_and_corrupt_usage_fail_closed(self):
        for usage in (None, {}, {'prompt_tokens': -1, 'completion_tokens': 0}):
            budget = Budget(self.root / ('usage-'+str(len(list(self.root.iterdir())))+'.sqlite3'))
            key = budget.reserve(100000)
            with self.assertRaises(BudgetPaused): budget.settle(key, usage, 'deepseek-flash', 100)
            self.assertTrue(budget.status()['paused'])

    def test_settings_no_key_echo_and_clear_does_not_reset_spend(self):
        settings = LocalSettings(self.root)
        public = settings.save({'model': 'deepseek-flash', 'enabled': True, 'api_key': 'fixture-secret'})
        self.assertNotIn('fixture-secret', json.dumps(public))
        self.assertNotIn('fixture-secret', settings.file.read_text())
        self.assertEqual(settings.model()._key, 'fixture-secret')
        settings.budget.reserve(1000)
        settings.save({'model': 'deepseek-v4-pro', 'enabled': True})
        self.assertEqual(settings.budget.status()['accounted_cny'], .000001)
        settings.save({'clear_key': True})
        self.assertIsNone(settings.model())
        self.assertEqual(settings.budget.status()['accounted_cny'], .000001)

    def test_budget_pause_does_not_consume_repair_errors(self):
        import test_control
        from embedded_agent.autonomy import AutonomousRunner
        fixture = test_control.ControlTests()
        fixture.setUp()
        class Provider:
            def decide(self, context): raise BudgetPaused('budget stop')
        try:
            run = fixture.prepared()
            result = AutonomousRunner(fixture.control, Provider()).step(run['id'])
            self.assertEqual(result['status'], 'budget_paused')
            self.assertEqual(fixture.control.load(run['id']).get('auto_errors', 0), 0)
        finally: fixture.tearDown()

    def test_rejected_key_can_be_corrected_without_resetting_budget(self):
        from urllib.error import HTTPError
        model = BudgetModel('deepseek-flash', 'fixture-secret', self.budget)
        with patch('embedded_agent.local_model.build_opener') as op:
            op.return_value.open.side_effect = HTTPError('https://api.deepseek.com/chat/completions', 401, 'no', {}, None)
            with self.assertRaises(BudgetPaused): model.generate(role='x', instruction='json', context={})
        self.assertEqual(self.budget.status()['accounted_cny'], 0)
        self.assertFalse(self.budget.status()['paused'])

    def test_acknowledge_unknown_keeps_full_reservation(self):
        key = self.budget.reserve(9_000_000_000)
        self.budget.uncertain(key)
        self.assertTrue(self.budget.status()['paused'])
        self.budget.acknowledge_uncertainty()
        self.assertFalse(self.budget.status()['paused'])
        self.assertEqual(self.budget.status()['accounted_cny'], 9)
        self.assertEqual(self.budget.status()['reserved_cny'], 9)
        with self.assertRaises(BudgetPaused): self.budget.reserve(1_000_000_001)

    def test_local_settings_http_and_same_origin_guards(self):
        import shutil
        import threading
        from urllib.request import urlopen, Request
        from urllib.error import HTTPError
        from embedded_agent.server import make_server
        source = Path(__file__).resolve().parents[1]
        (self.root / 'knowledge').mkdir()
        shutil.copyfile(source / 'knowledge/index.json', self.root / 'knowledge/index.json')
        server = make_server(self.root, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        url = 'http://127.0.0.1:' + str(server.server_port) + '/model/settings'
        try:
            body = json.dumps({'model': 'deepseek-flash', 'enabled': True, 'api_key': 'fixture-secret'}).encode()
            request = Request(url, body, {'Content-Type': 'application/json'})
            with urlopen(request) as response:
                raw = response.read()
                self.assertNotIn(b'fixture-secret', raw)
                self.assertTrue(json.loads(raw)['key_saved'])
            with urlopen(url) as response: self.assertTrue(json.load(response)['enabled'])
            hostile = Request(url, body, {'Content-Type': 'application/json', 'Origin': 'https://untrusted.invalid'})
            with self.assertRaises(HTTPError): urlopen(hostile)
        finally: server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__': unittest.main()
