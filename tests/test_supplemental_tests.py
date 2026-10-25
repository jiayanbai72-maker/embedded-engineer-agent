import unittest
from embedded_agent.supplemental_tests import combine

class SupplementalTests(unittest.TestCase):
    def test_keeps_original_assertions_and_isolates_reused_names(self):
        original='static int now; int main(void){assert(now==0);return 0;}'
        extra='static int now; int main(void){assert(now==1);return 0;}'
        files={'a.c':'production','test_a.c':original}
        combined=combine(files,{'late':extra,'missing':extra})
        body=combined['test_combined.c']
        self.assertIn(original,body)
        self.assertEqual(body.count(extra),2)
        self.assertIn('#define now audit_0_now',body)
        self.assertIn('#define now audit_1_now',body)
        self.assertIn('#define cal audit_0_cal',body)
        self.assertIn('audit_0_main()',body)
        self.assertIn('audit_1_main()',body)
        self.assertEqual(combined['a.c'],'production')
        self.assertEqual(files['test_a.c'],original)

    def test_rejects_ambiguous_test_entries(self):
        with self.assertRaises(ValueError):combine({'test_a.c':'no entry'}, {})
        with self.assertRaises(ValueError):combine({'test_a.c':'int main(void){return 0;}'}, {'x':'no entry'})
