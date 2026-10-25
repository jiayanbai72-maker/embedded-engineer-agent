import json
import tempfile
import unittest
from pathlib import Path
from embedded_agent.application import Application
from embedded_agent.domain import StageResult

ROOT = Path(__file__).absolute().parents[1]


class ArchitectureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'knowledge').mkdir()
        (self.root / 'knowledge/index.json').write_bytes((ROOT / 'knowledge/index.json').read_bytes())
        self.app = Application(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_persistence_and_unconfigured_model(self):
        project = self.app.store.create('做一个门窗状态监测器')
        result = self.app.workflow.step(project.id)
        self.assertEqual(result.stage, 'requirements')
        self.assertEqual(result.status, 'unsupported')
        restored = Application(self.root).store.load(project.id)
        self.assertEqual(restored.to_dict(), result.to_dict())
        self.assertEqual(self.app.workflow.step(project.id).revision, result.revision)

    def test_retry_does_not_skip_stage(self):
        project = self.app.store.create('控制照明')
        self.app.workflow.step(project.id)
        retried = self.app.workflow.retry(project.id)
        self.assertEqual(retried.status, 'ready')
        self.assertEqual(retried.stage, 'requirements')

    def test_knowledge_scope_and_tool_validation(self):
        self.assertEqual(self.app.knowledge.search('CMSIS'), [])
        self.assertTrue(self.app.knowledge.search('CMSIS', scope='ecosystem'))
        self.assertEqual(self.app.tools.execute('shell', {})['status'], 'unsupported')
        self.assertEqual(self.app.tools.execute('knowledge.search', {'query': 123})['status'], 'failed')
        self.assertEqual(self.app.tools.execute('knowledge.search', {'query': '需求'})['status'], 'passed')

    def test_path_traversal_rejected(self):
        with self.assertRaises(ValueError):
            self.app.store.load('../outside')

    def test_model_cannot_confirm_its_own_draft(self):
        class Model:
            def generate(self, **kwargs):
                return {'requirements': [{'id': 'REQ-1', 'description': '采集状态', 'acceptance': '状态改变可观察', 'origin': 'explicit'}],
                        'constraints': [], 'assumptions': [], 'questions': [], 'search_queries': ['需求'], 'confirmed': True}
        app = Application(self.root, model=Model())
        project = app.store.create('检测状态')
        result = app.workflow.step(project.id)
        self.assertEqual(result.status, 'needs_input')
        self.assertEqual(result.stage, 'requirements')
        with self.assertRaises(ValueError):
            app.workflow.retry(project.id)

    def test_invalid_output_and_exception_do_not_advance(self):
        class Model:
            def generate(self, **kwargs):
                return {'requirements': []}
        app = Application(self.root, model=Model())
        project = app.store.create('测量')
        self.assertEqual(app.workflow.step(project.id).status, 'failed')
        class BrokenAgent:
            def run(self, project, services):
                raise RuntimeError('sensitive internal detail')
        app.workflow.retry(project.id)
        app.workflow.agents['requirements'] = BrokenAgent()
        result = app.workflow.step(project.id)
        self.assertEqual(result.stage, 'requirements')
        self.assertNotIn('sensitive', json.dumps(result.to_dict()))

    def test_empty_pass_rejected_and_valid_stage_advances(self):
        class Agent:
            def __init__(self, artifact): self.artifact = artifact
            def run(self, project, services): return StageResult('passed', self.artifact)
        project = self.app.store.create('测试编排契约')
        self.app.workflow.agents['requirements'] = Agent({})
        self.assertEqual(self.app.workflow.step(project.id).status, 'failed')
        self.app.workflow.retry(project.id)
        self.app.workflow.agents['requirements'] = Agent({'test_fixture': True})
        result = self.app.workflow.step(project.id)
        self.assertEqual(result.stage, 'design')
        self.assertEqual(result.status, 'ready')


if __name__ == '__main__':
    unittest.main()
