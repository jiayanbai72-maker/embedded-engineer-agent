import importlib.util
import json
from pathlib import Path
import unittest
import test_architecture


class FullFlowTest(unittest.TestCase):
    setUp = test_architecture.ArchitectureTests.setUp
    tearDown = test_architecture.ArchitectureTests.tearDown

    def test_real_http_compile_fault_repair_restart_delivery(self):
        spec = importlib.util.spec_from_file_location('full_flow', test_architecture.ROOT / 'examples/run_full_flow.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result = module.run(self.root)
        self.assertEqual(result['host_tests'], 'passed')
        self.assertEqual(result['hardware'], 'not_run')
        self.assertTrue(Path(result['archive']).is_file())
        record = json.loads((self.root / 'runtime/full-flow/验收记录.json').read_text(encoding='utf-8'))
        self.assertEqual(record['injected_failure']['status'], 'failed')
        self.assertTrue(record['restart_restored'])
