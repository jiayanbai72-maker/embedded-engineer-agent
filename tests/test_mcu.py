import os
import unittest
from unittest.mock import patch
import importlib.util
from pathlib import Path
import sys
import test_architecture
from embedded_agent.mcu import ArmccCompiler, validate_sources


class MCUTests(unittest.TestCase):
    setUp = test_architecture.ArchitectureTests.setUp
    tearDown = test_architecture.ArchitectureTests.tearDown

    def test_source_and_target_boundaries(self):
        for files, cpu in (({'../test.c': 'int a;'}, 'Cortex-M3'), ({'x.h': 'int a;'}, 'Cortex-M3'), ({'x.c': 'int a;'}, 'unknown')):
            with self.assertRaises(ValueError): validate_sources(files, cpu)

    def test_missing_tool_does_not_claim_success(self):
        result = ArmccCompiler(self.root / 'missing.exe').compile({'test.c': 'int a;'}, 'Cortex-M3', self.root / 'output')
        self.assertEqual(result['status'], 'unsupported')
        self.assertEqual(result['firmware_link'], 'not_run')
        self.assertEqual(result['objects'], {})

    @unittest.skipUnless(os.environ.get('EMBEDDED_AGENT_ARMCC'), 'real ARMCC not configured')
    def test_real_compile_fault_repair_control_and_archive(self):
        example = test_architecture.ROOT / 'examples'
        sys.path.insert(0, str(example))
        try:
            spec = importlib.util.spec_from_file_location('mcu_demo', example / 'run_mcu_compile.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            result = module.run(self.root)
            self.assertEqual(result['compile'], 'passed')
            self.assertEqual(result['firmware_link'], 'not_run')
            self.assertTrue(Path(result['archive']).is_file())
        finally:
            sys.path.pop(0)
