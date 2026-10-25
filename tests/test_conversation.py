import tempfile
from pathlib import Path
from uuid import uuid4
import unittest
from unittest.mock import patch
from embedded_agent.conversation import Conversations
from embedded_agent.local_model import LocalSettings, BudgetModel, Budget


class ConversationTests(unittest.TestCase):
    def test_persist_isolate_and_no_duplicate_call(self):
        with tempfile.TemporaryDirectory() as folder:
            chat=Conversations(folder);project={'id':str(uuid4()),'revision':7,'description':'test','status':'documents_delivered','artifacts':{}}
            class Model:
                count=0
                def generate(self,**kwargs):
                    self.count+=1
                    self.context=kwargs['context']
                    return {'reply':'当前已交付，硬件未验证。'}
            model=Model();payload={'request_id':str(uuid4()),'message':'到哪一步？'}
            result=chat.send(project,payload,model)
            self.assertEqual(result['messages'][0]['status'],'answered')
            self.assertEqual(project['revision'],7)
            self.assertTrue(chat.send(project,payload,model)['reused'])
            self.assertEqual(model.count,1)
            self.assertEqual(Conversations(folder).history(project['id']),result['messages'])
            self.assertEqual(chat.history(str(uuid4())),[])
            with self.assertRaises(ValueError):chat.send(project,dict(payload,message='changed'),model)

    def test_failure_is_saved_without_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            chat=Conversations(folder);project={'id':str(uuid4()),'revision':1,'description':'x','status':'awaiting_analysis'}
            class Model:
                def generate(self,**kwargs):raise ValueError('budget paused')
            payload={'request_id':str(uuid4()),'message':'hello'}
            self.assertEqual(chat.send(project,payload,Model())['messages'][0]['status'],'failed')
            self.assertTrue(chat.send(project,payload,Model())['reused'])

    def test_custom_settings_and_key_destination(self):
        with tempfile.TemporaryDirectory() as folder, patch('embedded_agent.local_model.protect',side_effect=lambda value,decrypt=False:'secret' if decrypt else 'encrypted'):
            settings=LocalSettings(folder)
            settings.save({'api_key':'old','enabled':True})
            with self.assertRaises(ValueError):settings.save({'endpoint':'https://example.com/v1/chat/completions','model':'test','prices':{'hit':0,'input':1,'output':2}})
            public=settings.save({'endpoint':'https://example.com/v1/chat/completions','model':'test','prices':{'hit':0,'input':1,'output':2},'api_key':'new','enabled':True,'output_limit':2048})
            self.assertNotIn('encrypted_key',public)
            self.assertTrue(public['custom']);self.assertEqual(settings.model().endpoint,public['endpoint'])
            self.assertEqual(settings.model().output_limit,2048)
            with self.assertRaises(ValueError):settings.save({'prices':{'hit':0,'input':1,'output':float('nan')}})
            with self.assertRaises(ValueError):settings.save({'endpoint':'http://example.com','api_key':'new'})

    def test_custom_price_accounting(self):
        with tempfile.TemporaryDirectory() as folder:
            budget=Budget(Path(folder)/'budget.sqlite');key=budget.reserve(10000000)
            budget.settle(key,{'prompt_tokens':1000,'completion_tokens':100},'custom',2000,prices={'hit':0,'input':1,'output':2})
            self.assertAlmostEqual(budget.receipt(key)['accounted_cny'],.0012)


if __name__=='__main__':unittest.main()
