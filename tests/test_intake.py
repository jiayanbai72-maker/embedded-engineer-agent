import copy
import json
import unittest
import test_architecture
from unittest.mock import patch, MagicMock
from embedded_agent.analysis import validate_requirements, validate_comparison
from embedded_agent.model import ChatModel, configured_model


def draft():
    return {'requirements': [{'id': 'REQ-1', 'description': '检测状态', 'acceptance': '变化能观察', 'origin': 'explicit'}],
            'constraints': [{'name': '供电', 'value': '电池', 'origin': 'explicit'}],
            'assumptions': [], 'questions': [{'id': 'Q-1', 'question': '续航要求？', 'blocking': True}],
            'search_queries': ['需求', '功耗', '接口']}


def comparison():
    candidates = []
    for i, architecture in enumerate(('事件驱动主循环', 'RTOS任务与队列')):
        candidates.append({'id': f'PLAN-{i}', 'name': architecture, 'architecture': architecture,
                           'covers': ['REQ-1'], 'tradeoffs': ['资源与开发成本不同'], 'conditions': ['确认响应时间'],
                           'risks': ['续航未确定'], 'evidence_ids': ['GEN-ARCH-001'],
                           'chip_requirements': ['满足接口与功耗预算'], 'chip_options': []})
    return {'candidates': candidates, 'recommendation': {'candidate_id': 'PLAN-0', 'reason': '条件满足时优先简单方案'}}


class FakeModel:
    """Contract fixture, not a language understanding implementation."""
    def __init__(self): self.calls = []
    def generate(self, **kwargs):
        self.calls.append(kwargs)
        return draft() if kwargs['role'] == 'requirements' else comparison()


class IntakeTests(unittest.TestCase):
    setUp = test_architecture.ArchitectureTests.setUp
    tearDown = test_architecture.ArchitectureTests.tearDown
    def test_two_pass_pipeline_and_supplement(self):
        from embedded_agent.application import Application
        model = FakeModel()
        app = Application(self.root, model)
        project = app.analyze('设计电池供电的门窗提醒设备')
        self.assertEqual(project.status, 'needs_input')
        artifact = project.artifacts['requirements']
        self.assertEqual(artifact['comparison_status'], 'completed')
        self.assertEqual(artifact['comparison']['chip_selection'], 'not_finalized')
        self.assertEqual([c['role'] for c in model.calls], ['requirements', 'comparison'])
        self.assertTrue(all(c['scope'] == 'general' for c in artifact['evidence']))
        updated = app.supplement(project.id, '续航希望三个月')
        self.assertIn('三个月', updated.description)
        self.assertTrue(any(e.get('action') == 'superseded' for e in updated.events))

    def test_comparison_failure_preserves_draft(self):
        from embedded_agent.application import Application
        class Broken(FakeModel):
            def generate(self, **kwargs):
                return draft() if kwargs['role'] == 'requirements' else {'candidates': []}
        project = Application(self.root, Broken()).analyze('监测')
        self.assertEqual(project.artifacts['requirements']['comparison_status'], 'failed')
        self.assertTrue(project.artifacts['requirements']['requirements'])

    def test_invalid_ids_sources_and_chip_claims(self):
        req = draft()
        req['requirements'].append(copy.deepcopy(req['requirements'][0]))
        with self.assertRaises(ValueError): validate_requirements(req)
        evidence = self.app.knowledge.search('模块')
        for field in ('covers', 'evidence_ids'):
            result = comparison()
            result['candidates'][0][field] = ['nonexistent']
            with self.assertRaises(ValueError): validate_comparison(result, draft(), evidence)
        result = comparison()
        result['candidates'][0]['chip_options'] = [{'family': 'test-chip', 'status': 'verified', 'evidence_ids': ['GEN-ARCH-001']}]
        with self.assertRaises(ValueError): validate_comparison(result, draft(), evidence)

    def test_api_transport_and_sanitized_errors(self):
        payload = {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(draft())}}]}
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(payload).encode()
        opener = MagicMock()
        opener.open.return_value = response
        with patch('embedded_agent.model.build_opener', return_value=opener):
            result = ChatModel('https://example.org/v1/chat/completions', 'test', 'secret').generate(role='requirements', instruction='JSON', context={'description': '监测'})
        self.assertEqual(result, draft())
        request = opener.open.call_args.args[0]
        self.assertEqual(json.loads(request.data)['response_format'], {'type': 'json_object'})
        with self.assertRaises(ValueError): ChatModel('http://example.org', 'test', 'secret')
        with patch.dict('os.environ', {'EMBEDDED_AGENT_MODEL': 'test', 'EMBEDDED_AGENT_ENDPOINT': '', 'EMBEDDED_AGENT_API_KEY': ''}):
            with self.assertRaises(ValueError): configured_model()
