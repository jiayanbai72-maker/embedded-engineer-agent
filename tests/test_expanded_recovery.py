"""Exercise validation must feed real failures back without changing tests."""
import hashlib
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from run_expanded_tests import software_case, WRAP_TESTS


class RecoveryTests(unittest.TestCase):
    def test_invalid_source_is_repaired_with_frozen_tests(self):
        contexts = []

        class Model:
            def generate(self, **kwargs):
                contexts.append(kwargs['context'])
                if len(contexts) == 1:
                    return {'source': 'def broken('}
                return {'source': '''class Deadline:
 def __init__(self): self.start=None
 def arm(self,now_ms,delay_ms):
  if type(delay_ms) is not int or not 0<=delay_ms<2147483648: raise ValueError('delay')
  self.start=now_ms;self.delay=delay_ms
 def cancel(self): self.start=None
 def expired(self,now_ms): return self.start is not None and ((now_ms-self.start)&0xffffffff)>=self.delay
'''}

        result = software_case(Model(), 'clock_wrap')
        self.assertTrue(result['passed'])
        self.assertEqual(result['history'][0]['phase'], 'source_validation')
        self.assertIn('never closed', contexts[1]['last_result']['log'])
        self.assertEqual(contexts[0]['frozen_tests'], contexts[1]['frozen_tests'])
        self.assertEqual(result['tests_sha256'], hashlib.sha256(WRAP_TESTS.encode()).hexdigest())
        self.assertIn('Ran 4 tests', result['history'][-1]['log'])


if __name__ == '__main__':
    unittest.main()
