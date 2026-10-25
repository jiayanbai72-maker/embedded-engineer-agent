"""Real HTTP/service/tool acceptance; provider is a labeled deterministic fixture."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('closed_loop_acceptance', Path(__file__).resolve().parents[1] / 'tools/verify_agent_closed_loop.py')
matrix = importlib.util.module_from_spec(spec)
spec.loader.exec_module(matrix)


class ClosedLoopTests(unittest.TestCase):
    def check_case(self, index):
        with tempfile.TemporaryDirectory() as directory:
            result, archive = matrix.verify_case(Path(directory) / matrix.CASES[index]['id'], matrix.CASES[index])
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['hardware'], 'not_run')
        self.assertTrue(archive.startswith(b'PK'))
        self.assertEqual(len(result['confirmations']), 3)
        self.assertTrue(result['requirements_change_invalidated_delivery'])

    def test_environment_boundary_failure_restart_and_export(self): self.check_case(0)
    def test_actuator_compile_failure_restart_and_export(self): self.check_case(1)
    def test_logger_cache_scope_and_export(self): self.check_case(2)


if __name__ == '__main__': unittest.main()
