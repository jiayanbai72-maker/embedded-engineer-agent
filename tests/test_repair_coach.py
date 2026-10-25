import unittest
from embedded_agent.repair_coach import function_index,trace_source,parse_trace,brief

class CoachTests(unittest.TestCase):
    def test_renamed_helpers_and_loop_count_are_not_robot_specific(self):
        files={'generic.c':"""struct Driver { void (*write)(int); };
static void broadcast(struct Driver *d) {
 for(int lane=0;lane<5;lane++) { d->write(lane); }
}
void command(struct Driver *d) {
 broadcast(d);
}
"""}
        functions={x['function']:x for x in function_index(files)}
        self.assertTrue(functions['broadcast']['has_loop'])
        self.assertIn('d->write',functions['broadcast']['calls'])
        self.assertIn('broadcast',functions['command']['calls'])
        self.assertNotIn('robot',str(functions))

    def test_trace_does_not_instrument_strings_or_change_original(self):
        source='void f(struct D *d) { /* d->write(1); */ d->write(2); const char *s="d->write(3)"; }'
        out=trace_source(source,'fixture.c')
        self.assertEqual(out.count('DRAFT_CALL'),1)
        self.assertIn('/* d->write(1); */',out)
        self.assertIn('"d->write(3)"',out)
        self.assertIn('#line 1 "fixture.c"',out)

    def test_branch_trace_keeps_comparison_and_records_actual_values(self):
        from embedded_agent.repair_coach import parse_branches
        source='void tick(void) { unsigned elapsed; elapsed=2000; if(elapsed>=LIMIT && ready) act(); }'
        out=trace_source(source,'fixture.c')
        self.assertIn('DRAFT_BRANCH',out)
        self.assertIn('(elapsed>=LIMIT)',out)
        rows=parse_branches('DRAFT_BRANCH fixture.c:1 tick elapsed=2000 >= LIMIT=2000 result=1')
        self.assertEqual(rows[0]['left'],2000)
        self.assertTrue(rows[0]['result'])
        self.assertNotIn('DRAFT_BRANCH',trace_source('volatile unsigned elapsed; void t(void){if(elapsed>=LIMIT) f();}'))

    def test_trace_records_real_order_and_count(self):
        log='DRAFT_CALL fixture.c:3 broadcast d->write\n'*5
        out=parse_trace(log)
        self.assertEqual(out[0]['count'],5)
        self.assertEqual(out[0]['caller'],'broadcast')
        self.assertEqual(out[0]['line'],3)

    def test_cases_are_hints_and_not_claimed_as_current_evidence(self):
        result=brief({}, {'host_tests':{'assertion_diagnostic':{'expression':'pulses==2'}}})
        self.assertEqual(result['matched_lessons'][0]['id'],'callback_fanout')
        self.assertIn('不是当前证据',result['rules'])
