from copy import deepcopy
import json
import unittest
from embedded_agent.prompt_layout import messages,common_prefix_bytes

class PromptLayoutTests(unittest.TestCase):
    def test_c_contract_tests_precede_changing_repair_state_losslessly(self):
        a={'contract':'frozen spec','contract.h':'fixed header','test_contract.c':'assert(actual);','current_source':'old code','last_result':{'error':'one'}}
        b=deepcopy(a);b['current_source']='new code';b['last_result']={'error':'two'}
        original=deepcopy(a)
        first=messages('c_contract_writer','fixed',a,{})
        second=messages('c_contract_writer','fixed',b,{})
        self.assertEqual(first[:-1],second[:-1]);self.assertEqual(a,original)
        self.assertEqual(json.loads(first[-2]['content'])['immutable_inputs']['test_contract.c'],'assert(actual);')
        self.assertEqual(json.loads(second[-1]['content'])['current_state']['current_source'],'new code')
        self.assertEqual(json.dumps(first).count('assert(actual);'),1)

    def test_dynamic_reference_enums_reach_model_without_changing_static_prefix(self):
        static={'action_contracts':{'record_fact':{'schema':'base'}}}
        a={'action_contracts':{'record_fact':{'enum':['FACT-A']}},'allowed_actions':['record_fact']}
        b={'action_contracts':{'record_fact':{'enum':['FACT-B']}},'allowed_actions':['record_fact']}
        first=messages('engineering_decider','fixed',a,static)
        second=messages('engineering_decider','fixed',b,static)
        self.assertEqual(first[:2],second[:2])
        self.assertEqual(json.loads(first[-1]['content'])['current_state']['current_action_constraints']['record_fact']['enum'],['FACT-A'])
        self.assertEqual(json.loads(second[-1]['content'])['current_state']['current_action_constraints']['record_fact']['enum'],['FACT-B'])

    def test_unchanged_action_contract_is_not_duplicated(self):
        schema={'read':{'schema':'base'}}
        result=messages('engineering_decider','fixed',{'action_contracts':schema},{'action_contracts':schema})
        self.assertNotIn('current_action_constraints',json.loads(result[-1]['content'])['current_state'])
    def context(self):
        return {'files':{'robot.c':'int value=1;','robot.h':'void f(void);','test_robot.c':'int main(void){return 0;}'},
                'sha256':{'robot.c':'old','robot.h':'header','test_robot.c':'test'},
                'additional_frozen_tests':{'edge':'frozen test'},'feedback':{'error':'first'},'verification':{'status':'failed'}}

    def test_feedback_and_hash_changes_do_not_precede_tests_and_headers(self):
        a=self.context();original=deepcopy(a);b=deepcopy(a)
        b['feedback']['error']='second';b['verification']['status']='passed'
        first=messages('focused_repair','fixed',a,{})
        second=messages('focused_repair','fixed',b,{})
        self.assertEqual(first[:-1],second[:-1]);self.assertEqual(a,original)
        payloads=[json.loads(m['content']) for m in first[1:]]
        files=[p['source_file'] for p in payloads if 'source_file' in p]
        self.assertEqual([f['file'] for f in files],['test_robot.c','robot.h','robot.c'])
        self.assertEqual(files[-1]['sha256'],'old')
        self.assertEqual(payloads[-1]['current_state']['feedback'],a['feedback'])
        self.assertNotIn('files',payloads[-1]['current_state'])

    def test_production_edit_keeps_frozen_prefix_and_all_current_code(self):
        a=self.context();b=deepcopy(a);b['files']['robot.c']='int value=2;';b['sha256']['robot.c']='new'
        first=messages('focused_repair','fixed',a,{})
        second=messages('focused_repair','fixed',b,{})
        self.assertEqual(first[:-2],second[:-2])
        self.assertIn('int value=2;',second[-2]['content'])
        self.assertIn('"sha256":"new"',second[-2]['content'])
        self.assertNotIn('int value=1;',json.dumps(second))
        self.assertGreater(common_prefix_bytes(first,second)['shared_prefix_bytes'],0)

    def test_baseline_is_not_duplicated_and_dynamic_authority_is_kept(self):
        context={'project':{'description':'distinct description','revision':4,'artifacts':{'requirements':{'needs':['distinct req']},'other':'evidence'}},
                 'allowed_actions':['ask'],'action_contracts':{'ignored_static_copy':True}}
        original=deepcopy(context);result=messages('engineering_decider','fixed',context,{'schema':'kept'})
        text=json.dumps(result,ensure_ascii=False)
        self.assertEqual(text.count('distinct description'),1)
        self.assertEqual(text.count('distinct req'),1)
        self.assertIn('allowed_actions',result[-1]['content']);self.assertIn('evidence',text)
        self.assertEqual(context,original)

    def test_empty_file_shape_does_not_lose_unexpected_data(self):
        result=messages('focused_repair','fixed',{'files':'invalid','sha256':{'x':'y'}},{})
        state=json.loads(result[-1]['content'])['current_state']
        self.assertEqual(state['files'],'invalid');self.assertEqual(state['sha256'],{'x':'y'})
