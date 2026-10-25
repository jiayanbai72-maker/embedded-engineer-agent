import unittest
from copy import deepcopy
from embedded_agent.draft_regression import checkpoint,preserve
from embedded_agent.draft_verification import source_hash
from embedded_agent.repair_coach import trace_assertions,assertion_progress

class RegressionTests(unittest.TestCase):
    def baseline(self):
        files={'a.c':'int a;','test_a.c':'assert(a);'}
        return {'engineering_draft':{'firmware':{'files':files}},'draft_verification':{'status':'failed','source_sha256':source_hash(files),'host_tests':{'passed_assertions':['test_a.c#1','test_a.c#2'],'assertion_progress_available':True}}}

    def test_measured_regression_restores_exact_checkpoint(self):
        a=self.baseline();before=deepcopy(a);checkpoint(a)
        a['engineering_draft']['firmware']['files']['a.c']='int b;'
        candidate={'status':'failed','source_sha256':source_hash(a['engineering_draft']['firmware']['files']),'host_tests':{'passed_assertions':['test_a.c#1'],'assertion_progress_available':True}}
        self.assertTrue(preserve(a,candidate))
        self.assertEqual(a['engineering_draft'],before['engineering_draft'])
        self.assertEqual(a['draft_verification'],before['draft_verification'])
        self.assertEqual(a['draft_regression']['lost_passed_assertions'],['test_a.c#2'])
        self.assertEqual(a['draft_regression_history'][-1]['verification'],candidate)

    def test_improvement_and_unknown_progress_do_not_false_rollback(self):
        for host in ({'passed_assertions':['test_a.c#1','test_a.c#2','test_a.c#3'],'assertion_progress_available':True},{}):
            a=self.baseline();checkpoint(a);a['engineering_draft']['firmware']['files']['a.c']='int b;'
            self.assertFalse(preserve(a,{'status':'failed','host_tests':host}))
        a=self.baseline();checkpoint(a);a['engineering_draft']['firmware']['files']['test_a.c']='assert(b);'
        self.assertFalse(preserve(a,{'status':'failed','host_tests':{'assertion_progress_available':True}}))

    def test_assertion_observer_evaluates_original_expression_once(self):
        src='int f(void){assert(x++ == 1); if(y) assert(g(1,2)); return 0;}'
        out=trace_assertions(src,'test_x.c')
        self.assertEqual(out.count('x++'),1)
        self.assertEqual(out.count('g(1,2)'),1)
        self.assertEqual(out.count('DRAFT_ASSERT_PASS'),2)
        self.assertEqual(assertion_progress('DRAFT_ASSERT_PASS test_x.c#2\nDRAFT_ASSERT_PASS test_x.c#2'),['test_x.c#2'])
