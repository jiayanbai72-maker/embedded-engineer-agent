import unittest
from embedded_agent.assertion_diagnostics import instrument,values

class DiagnosticTests(unittest.TestCase):
    def test_simple_failure_keeps_assertion_and_probes_without_mutation(self):
        source='void f(void) { assert(pulses==2&&last_us==1500&&c.busy); }\n'
        files={'test_x.c':source};out=instrument(files,'Assertion failed: pulses==2&&last_us==1500&&c.busy, file test_x.c, line 1')
        self.assertEqual(files['test_x.c'],source)
        self.assertEqual(out['probes'],['pulses','last_us','c.busy'])
        self.assertIn('assert(pulses==2&&last_us==1500&&c.busy)',out['instrumented_source'])
        self.assertIn('#line 1',out['instrumented_source'])
        self.assertEqual(values('DRAFT_DIAG pulses=4\nDRAFT_DIAG c.busy=0'),{'pulses':4,'c.busy':0})

    def test_duplicate_identical_assert_on_same_line_is_ambiguous(self):
        self.assertIsNone(instrument({'test_x.c':'assert(x==1); x=2; assert(x==1);'},'Assertion failed: x==1, file test_x.c, line 1'))

    def test_side_effects_calls_and_non_test_are_not_instrumented(self):
        for expr in ('f()==2','x++==2','x=2','p->x==2','a[0]==2'):
            self.assertIsNone(instrument({'test_x.c':'assert('+expr+');'},'Assertion failed: '+expr+', file test_x.c, line 1'))
        self.assertIsNone(instrument({'main.c':'assert(x);'},'Assertion failed: x, file main.c, line 1'))


class StallTests(unittest.TestCase):
    def test_repeated_measured_failure_stops_only_distinct_source_versions(self):
        from embedded_agent.runtime_policy import diagnostic_stall
        def receipt(source,value):return {'action':'draft_verify','status':'executed','tool_result':{'status':'failed','source_sha256':source,'host_tests':{'assertion_diagnostic':{'file':'test.c','expression':'x==2','actual_values':{'x':value}}}}}
        self.assertTrue(diagnostic_stall({'observations':[receipt('a',3),receipt('b',3)]}))
        self.assertFalse(diagnostic_stall({'observations':[receipt('a',3),receipt('b',2)]}))
        self.assertFalse(diagnostic_stall({'observations':[receipt('a',3),receipt('a',3)]}))
