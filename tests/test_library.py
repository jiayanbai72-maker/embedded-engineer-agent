"""Synthetic fixtures test provenance and gating, not real component specifications."""
import hashlib
import json
import threading
import unittest
import urllib.request
import test_architecture
from embedded_agent.library import DocumentLibrary, ParameterEvidence
from embedded_agent.selection import evaluate_selection
from embedded_agent.service import EngineeringService
from embedded_agent.control import DecisionController
from embedded_agent.server import make_server


class LibraryTests(unittest.TestCase):
    def setUp(self):
        test_architecture.ArchitectureTests.setUp(self)
        folder=self.root/'knowledge/official'; folder.mkdir()
        self.source=folder/'fixture.pdf'; self.source.write_bytes(b'%PDF synthetic provenance fixture only')
        self.content='Synthetic test only.\n\f\nSupply voltage ranges from 1.8 V to 3.6 V. Output range is 3.0 V to 3.3 V.\n'
        self.text=folder/'fixture.txt'; self.text.write_text(self.content,encoding='utf-8')
        split=self.content.index('Supply')
        (folder/'fixture.pages.json').write_text(json.dumps([{'page':1,'start':0,'end':split},{'page':2,'offset':split,'length':len(self.content)-split}]))
        doc={'id':'DOC-fixture','title':'TEST-CHIP synthetic datasheet','category':'fixture',
             'file':'knowledge/official/fixture.pdf','text':'knowledge/official/fixture.txt',
             'page_index':'knowledge/official/fixture.pages.json','pages':2,
             'sha256':hashlib.sha256(self.source.read_bytes()).hexdigest(),
             'source_urls':['https://example.invalid/synthetic-only'],'retrieval_eligible':True}
        (folder/'catalog.json').write_text(json.dumps({'documents':[doc]}))
        self.library=DocumentLibrary(self.root); self.library.build()
        self.params=ParameterEvidence(self.root,self.library)

    tearDown=test_architecture.ArchitectureTests.tearDown

    def review(self,parameter='input_max_v',value=3.6):
        return self.params.review({'document_id':'DOC-fixture','page':2,'model':'TEST-CHIP','parameter':parameter,
            'value':value,'unit':'V','conditions':'synthetic test only',
            'quote':'Supply voltage ranges from 1.8 V to 3.6 V.', 'reviewer':'test fixture',
            'rationale':'Synthetic bounds used only to test provenance enforcement.','confirmed':True})

    def checked_proposal(self):
        inputs={'input_min_v':1.8,'input_max_v':3.6,'output_min_v':3.0,'output_max_v':3.3}
        bindings={}
        for key,value in inputs.items():
            p=self.review(key,value)
            bindings[key]={'parameter_id':p['id'],'model':p['model'],'conditions':p['conditions']}
        return {'checks':[{'id':'V','kind':'voltage','inputs':inputs,'parameter_bindings':bindings}]}

    def test_search_returns_exact_page_and_restores_after_restart(self):
        results=self.library.search('TEST-CHIP 供电电压')
        self.assertEqual(results[0]['page'],2)
        self.assertFalse(results[0]['reviewed'])
        self.assertTrue(self.library.search('TESTCHIP voltage'))
        self.assertIn('p.2',results[0]['citation'])
        page=DocumentLibrary(self.root).page('DOC-fixture',2)
        self.assertEqual(page['text'],self.content[self.content.index('Supply'):])
        self.assertEqual(DocumentLibrary(self.root).status()['documents'],1)
        self.assertEqual(self.library.search('nonexistent chip'),[])
        with self.assertRaises(ValueError): self.library.page('DOC-fixture',99)
        with self.assertRaises(ValueError): self.library.safe('../outside')

    def test_quote_must_belong_to_selected_page_and_review_persists(self):
        p=self.review()
        self.assertEqual(ParameterEvidence(self.root,self.library).get(p['id'])['value'],3.6)
        bad=dict(p,confirmed=True,page=1)
        with self.assertRaises(ValueError): self.params.review(bad)
        bad=dict(p,confirmed=False)
        with self.assertRaises(ValueError): self.params.review(bad)
        self.text.write_text(self.content+' tampered',encoding='utf-8')
        with self.assertRaises(ValueError): self.params.get(p['id'])
        self.assertFalse(self.params.list()[0]['valid'])

    def test_registry_binding_prevents_forgery_wrong_values_units_meanings_and_conditions(self):
        p=self.checked_proposal()
        self.assertEqual(evaluate_selection(p,self.params.get)['status'],'passed')
        check=p['checks'][0]
        check['inputs']['input_max_v']=4
        self.assertEqual(evaluate_selection(p,self.params.get)['status'],'needs_evidence')
        check['inputs']['input_max_v']=3.6
        check['parameter_bindings']['input_max_v']['conditions']='different'
        self.assertEqual(evaluate_selection(p,self.params.get)['status'],'needs_evidence')
        check['parameter_bindings']['input_max_v']['conditions']='synthetic test only'
        check['parameter_bindings']['input_max_v']['parameter_id']=check['parameter_bindings']['output_max_v']['parameter_id']
        self.assertEqual(evaluate_selection(p,self.params.get)['status'],'needs_evidence')
        check.pop('parameter_bindings')
        p['evidence']=[{'id':'FAKE','reviewed':True,'reviewer':'LLM','snapshot_sha256':'invented','section':'x','scope_note':'x'}]
        check['evidence_ids']=['FAKE']
        self.assertEqual(evaluate_selection(p,self.params.get)['status'],'needs_evidence')

    def test_controller_search_observe_and_idempotence_without_project_mutation(self):
        service=EngineeringService(self.root); project=service.create('synthetic lookup')
        controller=DecisionController(service); run=controller.create(project['id'])
        decision={'id':'search-1','project_revision':project['revision'],'action':'search_documents',
            'arguments':{'query':'TEST-CHIP voltage'},'rationale':'Find source before choosing parts',
            'expected':'A physical page citation, not verified parameters','source':'synthetic test'}
        controller.submit(run['id'],run['revision'],decision)
        finished=controller.tick(run['id'])
        self.assertEqual(finished['observations'][0]['tool_result']['matches'][0]['page'],2)
        self.assertEqual(service.get(project['id'])['revision'],project['revision'])
        controller.tick(run['id'])
        self.assertEqual(controller.load(run['id'])['steps'],1)

    def test_http_search_page_original_and_review(self):
        server=make_server(self.root,0); thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        def request(path,payload=None):
            req=urllib.request.Request(f'http://127.0.0.1:{server.server_port}'+path,
               data=None if payload is None else json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
            with urllib.request.urlopen(req,timeout=5) as response: return response.read()
        try:
            matches=json.loads(request('/knowledge/search',{'query':'TEST-CHIP voltage'}))['matches']
            self.assertEqual(matches[0]['page'],2)
            self.assertEqual(request('/knowledge/documents/DOC-fixture/file'),self.source.read_bytes())
            page=json.loads(request('/knowledge/page',{'document_id':'DOC-fixture','page':2}))
            self.assertIn('3.6',page['text'])
            self.assertTrue(json.loads(request('/knowledge/status'))['ready'])
            self.assertEqual(json.loads(request('/knowledge/parameters'))['parameters'],[])
        finally: server.shutdown(); server.server_close(); thread.join()

    def test_actual_source_change_blocks_citation(self):
        p=self.review()
        self.source.write_bytes(b'changed')
        with self.assertRaises(ValueError): self.library.search('TEST-CHIP voltage')
        with self.assertRaises(ValueError): self.params.get(p['id'])

    def test_service_uses_registry_then_continues_and_exports_evidence(self):
        service=EngineeringService(self.root)
        project=service.create('Synthetic registry integration')
        analysis=json.loads((test_architecture.ROOT/'examples/analyst-door-monitor.json').read_text(encoding='utf-8'))
        for operation,payload in [('analysis',analysis),('confirm',{'confirmed':True}),('select',{'candidate_id':'PLAN-NEAR'})]:
            project=service.update(project['id'],project['revision'],operation,payload)
        p=self.checked_proposal()
        project=service.update(project['id'],project['revision'],'selection_check',{'proposal':p})
        self.assertEqual(project['status'],'selection_checked')
        self.assertEqual(len(project['artifacts']['selection_check']['checks'][0]['resolved_evidence']),4)
        self.source.write_bytes(b'changed')
        with self.assertRaises(ValueError): service.update(project['id'],project['revision'],'continue_selection',{'confirmed':True})
        self.source.write_bytes(b'%PDF synthetic provenance fixture only')
        project=service.update(project['id'],project['revision'],'continue_selection',{'confirmed':True})
        self.assertEqual(project['status'],'ready_delivery')
        project=service.update(project['id'],project['revision'],'execute',{})
        from io import BytesIO
        from zipfile import ZipFile
        with ZipFile(BytesIO(service.download(project['id']))) as archive:
            report=json.loads(archive.read('selection-check.json'))
            self.assertEqual(report['evidence_mode'],'local_parameter_registry')
