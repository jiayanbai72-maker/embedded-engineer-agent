import hashlib
import json
import unittest
import test_library
from embedded_agent.web_documents import extract
from embedded_agent.planning import validate


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_library.LibraryTests(); self.fixture.setUp()

    def tearDown(self): self.fixture.tearDown()

    def test_long_query_stays_anchored_to_model(self):
        library = self.fixture.library
        catalog = json.loads(library.catalog.read_text())
        catalog['documents'][0]['title'] = 'TEST123 datasheet'
        library.catalog.write_text(json.dumps(catalog)); library.build()
        results = library.search('TEST123 datasheet supply voltage imaginary extra words')
        self.assertTrue(results)
        self.assertEqual(results[0]['document_id'], 'DOC-fixture')
        self.assertEqual(results[0]['retrieval_strategy'], 'model_anchored_topic_fallback')
        self.assertFalse(library.search('UNKNOWN999 supply voltage extra words'))

    def test_saved_webpage_becomes_searchable_without_pdf_pages(self):
        library = self.fixture.library
        html = library.root/'knowledge/official/servo.html'
        html.write_text('<html><title>SG90 synthetic specification</title><script>not evidence</script><body><h1>SG90</h1><p>Operating voltage 4.8 V. Synthetic text only. '+('fixture specification '*12)+'</p></body></html>')
        catalog = json.loads(library.catalog.read_text())
        catalog['documents'].append({'id':'DOC-web-fixture','title':'source-page.html','category':'synthetic',
            'file':html.relative_to(library.root).as_posix(),'sha256':hashlib.sha256(html.read_bytes()).hexdigest(),
            'retrieval_eligible':False,'source_urls':['https://example.invalid/fixture']})
        library.catalog.write_text(json.dumps(catalog))
        result = library.ingest_saved_webpages()
        self.assertIn('DOC-web-fixture', result['imported']); library.build()
        hits = library.search('SG90 voltage')
        self.assertTrue(hits); self.assertIsNone(hits[0]['page']); self.assertFalse(hits[0]['reviewed'])
        page = library.page('DOC-web-fixture',None)
        self.assertNotIn('not evidence', page['text'])
        self.assertFalse(library.ingest_saved_webpages()['imported'])

    def test_plan_errors_have_exact_task_path(self):
        plan = {'goal':'x','rationale':'x','source':'fixture','tasks':[{'id':'T','action':'build','depends_on':[],'completion':{'status':'executed'}}]}
        with self.assertRaisesRegex(ValueError, r'plan.tasks\[0\].title'):
            validate(plan, {'build'})


if __name__=='__main__': unittest.main()
