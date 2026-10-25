"""Synthetic claims only; no API requests or real component certifications."""
import unittest
import json
import hashlib
from unittest.mock import MagicMock, patch
import test_library as fixtures
from embedded_agent.online_research import OnlineResearch


class AutonomousEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.LibraryTests();self.fixture.setUp()
        self.claim=dict(document_id='DOC-fixture',page=2,model='TEST-CHIP',parameter='input_max_v',value=3.6,unit='V',conditions='synthetic test only',quote='Supply voltage ranges from 1.8 V to 3.6 V.',rationale='Synthetic provenance check only.')
        self.model=MagicMock()
        self.model.generate.return_value=dict(model_match=True,parameter_match=True,unit_match=True,conditions_match=True,supported=True,rationale='The synthetic supply range explicitly ends at 3.6 V.')

    def tearDown(self):self.fixture.tearDown()

    def test_reads_original_without_user_or_network(self):
        web=OnlineResearch(self.fixture.root,self.fixture.library)
        with patch('embedded_agent.online_research.fetch_public') as network:
            result=web.autonomous_research('fixture-project','voltage')
        network.assert_not_called()
        self.assertTrue(result['autonomous']);self.assertFalse(result['human_research_required'])
        self.assertIn('Supply voltage',result['original_pages'][0]['text'])
        self.assertFalse(result['parameters_verified'])

    def test_accepted_claim_is_recorded_and_reused(self):
        first=self.fixture.params.auto_review(self.claim,self.model)
        self.assertEqual(first['status'],'recorded')
        self.assertEqual(first['parameter']['review_kind'],'agent_model_review_with_programmatic_source_checks')
        self.assertFalse(first['hardware_verified'])
        second=self.fixture.params.auto_review(self.claim,self.model)
        self.assertTrue(second['cached']);self.model.generate.assert_called_once()

    def test_invalid_claims_rejected_before_paid_check(self):
        for changes in ({'value':9.9},{'unit':'mA'},{'model':'OTHERCHIP'},{'quote':'Imaginary supply voltage is 9.9 V.'}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                self.fixture.params.auto_review(dict(self.claim,**changes),self.model)
        self.model.generate.assert_not_called()

    def test_ambiguous_or_malformed_check_never_approves(self):
        for answer in (None,[],{'supported':False},dict(self.model.generate.return_value,conditions_match=False)):
            self.model.generate.return_value=answer
            result=self.fixture.params.auto_review(self.claim,self.model)
            self.assertEqual(result['status'],'needs_evidence');self.assertFalse(result['human_research_required'])
        self.assertEqual(self.fixture.params.list(),[])

    def test_chip_family_search_finds_package_variant_without_generic_match(self):
        catalog=self.fixture.library.catalog
        data=json.loads(catalog.read_text(encoding='utf-8'))
        data['documents'][0]['title']='STM32L031K6 synthetic datasheet'
        catalog.write_text(json.dumps(data),encoding='utf-8');self.fixture.library.build()
        hits=self.fixture.library.search('STM32L031 datasheet supply voltage actual operating conditions')
        self.assertTrue(hits)
        self.assertEqual(hits[0]['retrieval_strategy'],'model_anchored_topic_fallback')
        self.assertFalse(self.fixture.library.search('STM32F103 datasheet supply voltage'))

    def test_quote_id_uses_exact_source_and_rejects_stale_id(self):
        page=self.fixture.library.page('DOC-fixture',2)
        claim=dict(self.claim,quote_id=page['quote_blocks'][0]['quote_id']);claim.pop('quote')
        result=self.fixture.params.auto_review(claim,self.model)
        self.assertEqual(result['parameter']['quote'],page['quote_blocks'][0]['text'])
        with self.assertRaises(ValueError):self.fixture.params.auto_review(dict(claim,quote_id='stale'),self.model)

    def test_written_channel_count_has_semantic_review(self):
        self.fixture.text.write_text(self.fixture.content+' TEST-CHIP timer features four independent channels for PWM output.',encoding='utf-8')
        index=self.fixture.text.with_suffix('.pages.json')
        # Extend the synthetic second physical page after adding its statement.
        rows=json.loads(index.read_text());rows[1]['length']=len(self.fixture.text.read_text(encoding='utf-8'))-rows[1]['offset'];index.write_text(json.dumps(rows))
        self.fixture.library.build()
        claim=dict(self.claim,value=4,unit='channels',parameter='pwm_channels',quote='TEST-CHIP timer features four independent channels for PWM output.')
        result=self.fixture.params.auto_review(claim,self.model)
        self.assertEqual(result['status'],'recorded');self.model.generate.assert_called_once()

    def test_text_relation_is_separate_from_numeric_parameters(self):
        page=self.fixture.library.page('DOC-fixture',2)
        claim=dict(document_id='DOC-fixture',page=2,quote_id=page['quote_blocks'][0]['quote_id'],model='TEST-CHIP',subject='Supply',predicate='voltage',object='3.6',conditions='Synthetic relation only',rationale='Synthetic provenance test')
        result=self.fixture.params.auto_fact(claim,self.model)
        self.assertEqual(result['status'],'recorded');self.assertFalse(result['hardware_verified'])
        self.assertTrue(self.fixture.params.facts()[0]['valid'])
        self.assertEqual(self.fixture.params.list(),[])
        self.assertTrue(self.fixture.params.auto_fact(claim,self.model)['cached']);self.model.generate.assert_called_once()
        self.fixture.text.write_text('changed',encoding='utf-8')
        self.assertFalse(self.fixture.params.facts()[0]['valid'])

    def test_relation_cooccurrence_does_not_bypass_semantic_rejection(self):
        page=self.fixture.library.page('DOC-fixture',2)
        claim=dict(document_id='DOC-fixture',page=2,quote_id=page['quote_blocks'][0]['quote_id'],model='TEST-CHIP',subject='Supply',predicate='voltage',object='3.6',conditions='Synthetic relation only',rationale='Synthetic test')
        self.model.generate.return_value={'supported':False,'rationale':'Wrong table relationship'}
        self.assertEqual(self.fixture.params.auto_fact(claim,self.model)['status'],'needs_evidence')
        self.assertEqual(self.fixture.params.facts(),[])
        with self.assertRaises(ValueError):self.fixture.params.auto_fact(dict(claim,subject='PA99'),self.model)

    def test_package_is_typed_relation_but_requires_semantic_support(self):
        page=self.fixture.library.page('DOC-fixture',2)
        claim=dict(document_id='DOC-fixture',page=2,quote_id=page['quote_blocks'][0]['quote_id'],model='TEST-CHIP',subject='Supply',predicate='package',object='voltage',conditions='Synthetic invalid package test',rationale='Test semantic rejection')
        self.model.generate.return_value={'supported':False,'rationale':'This is not a pin definition table.'}
        with self.assertRaises(ValueError):self.fixture.params.auto_fact(claim,self.model)
        self.model.generate.assert_not_called();self.assertEqual(self.fixture.params.facts(),[])

    def test_pdf_table_preserves_rows_and_rotated_package_header(self):
        from reportlab.pdfgen import canvas
        c=canvas.Canvas(str(self.fixture.source));c.drawString(50,700,'Synthetic page one');c.showPage()
        c.drawString(50,700,'TEST-CHIP synthetic pin table')
        for x in (50,150,250):c.line(x,400,x,490)
        for y in (400,430,490):c.line(50,y,250,y)
        c.drawString(60,450,'Pin');c.saveState();c.translate(190,437);c.rotate(90);c.drawString(0,0,'LQFP32');c.restoreState()
        c.drawString(60,410,'PA2');c.drawString(160,410,'8');c.save()
        catalog=self.fixture.library.catalog;data=json.loads(catalog.read_text(encoding='utf-8'))
        data['documents'][0]['sha256']=hashlib.sha256(self.fixture.source.read_bytes()).hexdigest()
        catalog.write_text(json.dumps(data),encoding='utf-8');self.fixture.library.build()
        page=self.fixture.library.page('DOC-fixture',2,source_view='layout')
        grid=json.loads(page['text'])['tables'][0]
        self.assertEqual(grid['rows'][0][1],'LQFP32')
        self.assertEqual(grid['rows'][1],['PA2','8'])
        self.assertTrue(grid['rotation_corrected_cells'])
        claim=dict(document_id='DOC-fixture',page=2,source_view='layout',quote_id=page['quote_blocks'][0]['quote_id'],model='TEST-CHIP',subject='PA2',predicate='package',object='LQFP32',conditions='Synthetic fixture only',rationale='Synthetic table provenance')
        result=self.fixture.params.auto_fact(claim,self.model)
        self.assertEqual(result['status'],'recorded')
        self.assertEqual(result['fact']['source_view'],'layout')


if __name__=='__main__':unittest.main()
