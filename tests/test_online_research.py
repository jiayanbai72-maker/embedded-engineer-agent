from pathlib import Path
import json
import unittest
from unittest.mock import patch,MagicMock
from uuid import uuid4
from embedded_agent.online_research import OnlineResearch,canonical,public_addresses,fetch_public,atomic
import test_library as fixtures

class OnlineResearchTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.LibraryTests();self.fixture.setUp()
        self.root=self.fixture.root;self.library=self.fixture.library
        self.web=OnlineResearch(self.root,self.library);self.pid=str(uuid4())

    def tearDown(self):self.fixture.tearDown()

    def enable(self):self.web.configure({'enabled':True,'domains':['example.com'],'confirmed':True})

    def rss(self):
        return {'url':'https://www.bing.com/search','mime':'application/rss+xml','raw':b'<rss><channel><item><title>NEWCHIP123 official</title><link>https://example.com/spec</link></item><item><link>https://evil.test/spec</link></item></channel></rss>'}

    def html(self):
        return {'url':'https://example.com/spec','mime':'text/html','raw':('<html><title>NEWCHIP123 manufacturer specification</title><p>'+('NEWCHIP123 supply voltage operating conditions. '*12)+'</p></html>').encode()}

    def test_disabled_and_local_matches_never_touch_network(self):
        with patch('embedded_agent.online_research.fetch_public') as network:
            result=self.web.research(self.pid,'NEWCHIP123 missing')
            self.assertEqual(result['online']['status'],'not_configured')
            self.assertEqual(self.web.research(self.pid,'voltage')['status'],'references_found')
            network.assert_not_called()

    def test_search_import_reindex_and_citations_without_parameter_approval(self):
        self.enable()
        with patch('embedded_agent.online_research.fetch_public',side_effect=[self.rss(),self.html()]) as network:
            result=self.web.research(self.pid,'NEWCHIP123 voltage')
            self.assertEqual(network.call_count,2)
            cached=self.web.search(self.pid,'NEWCHIP123 voltage')
            self.assertTrue(cached['cached']);self.assertEqual(network.call_count,2)
        self.assertTrue(result['matches']);self.assertFalse(result['parameters_verified'])
        imported=result['imports'][0];self.assertEqual(imported['status'],'imported')
        page=self.library.page(imported['document_id'],None)
        self.assertEqual(page['source_url'],'https://example.com/spec');self.assertIsNone(page['page'])
        self.assertFalse(self.library.document(imported['document_id'])['reviewed'])
        self.assertNotIn('evil.test',json.dumps(cached['matches']))

    def test_network_failure_is_cached_and_bounded(self):
        self.enable()
        with patch('embedded_agent.online_research.fetch_public',side_effect=TimeoutError('offline')) as network:
            first=self.web.search(self.pid,'NEWCHIP123');second=self.web.search(self.pid,'NEWCHIP123')
            self.assertEqual(first['status'],'network_unavailable');self.assertTrue(second['cached'])
            self.assertEqual(network.call_count,1)
        config=self.web.settings();config['search_limit']=1;atomic(self.web.config,config)
        with patch('embedded_agent.online_research.fetch_public') as network:
            self.assertEqual(self.web.search(self.pid,'different')['status'],'limit_reached');network.assert_not_called()

    def test_user_retry_keeps_attempt_quota(self):
        self.enable()
        with patch('embedded_agent.online_research.fetch_public',side_effect=TimeoutError('offline')):
            self.web.search(self.pid,'NEWCHIP123')
        with self.assertRaises(ValueError):self.web.retry_failed(self.pid,False)
        result=self.web.retry_failed(self.pid,True);self.assertFalse(result['quotas_reset'])
        self.assertEqual(self.web.state(self.pid)['search_attempts'],1)
        with patch('embedded_agent.online_research.fetch_public',return_value=self.rss()):
            self.web.search(self.pid,'NEWCHIP123')
        self.assertEqual(self.web.state(self.pid)['search_attempts'],2)

    def test_visible_pdf_links_remain_candidates(self):
        from embedded_agent.web_documents import pdf_links
        raw='<a href="/resource/en/datasheet/chip.pdf">datasheet</a><a href="javascript:bad">bad</a><script>https://invented.example/hidden.pdf</script>'
        self.assertEqual(pdf_links(raw,'https://example.com/product'),['https://example.com/resource/en/datasheet/chip.pdf'])

    def test_delivery_freezes_research_history(self):
        from embedded_agent.service import EngineeringService
        import io
        from zipfile import ZipFile
        service=EngineeringService(self.root);p=service.app.store.create('Synthetic research archive fixture')
        p.status='ready_delivery';service.app.store.save(p)
        atomic(service.web.state_path(p.id),{'searches':{'a':{'query':'first','status':'no_matches'}},'documents':{},'events':[]})
        saved=service.update(p.id,p.revision,'execute',{})
        before=service.download(p.id)
        atomic(service.web.state_path(p.id),{'searches':{'a':{'query':'second','status':'no_matches'}},'documents':{},'events':[]})
        self.assertEqual(service.download(p.id),before)
        with ZipFile(io.BytesIO(before)) as archive:
            self.assertEqual(json.loads(archive.read('online-research.json'))['searches'][0]['query'],'first')

    def test_catalog_restored_if_indexing_fails(self):
        self.enable();before=self.library.catalog.read_bytes()
        with patch('embedded_agent.online_research.fetch_public',return_value=self.html()),patch.object(self.library,'build',side_effect=ValueError('fixture failure')):
            result=self.web.import_url(self.pid,'https://example.com/spec')
        self.assertEqual(result['status'],'import_failed');self.assertEqual(self.library.catalog.read_bytes(),before)

    def test_challenge_page_and_unapproved_urls_are_not_imported(self):
        self.enable();before=self.library.catalog.read_bytes()
        with self.assertRaises(ValueError):self.web.import_url(self.pid,'https://example.com.attacker.test/spec')
        challenge=self.html();challenge['raw']=b'<title>Just a moment</title><p>captcha verification required</p>'
        with patch('embedded_agent.online_research.fetch_public',return_value=challenge):
            result=self.web.import_url(self.pid,'https://example.com/spec')
        self.assertEqual(result['status'],'import_failed');self.assertEqual(self.library.catalog.read_bytes(),before)

    def test_https_credentials_ports_and_private_dns_are_blocked(self):
        for url in ['http://example.com/a','https://user:secret@example.com/a','https://example.com:8443/a','https://localhost/a']:
            with self.assertRaises(ValueError):canonical(url)
        for ip in ['127.0.0.1','10.0.0.1','169.254.169.254','::1','192.168.1.1']:
            with patch('embedded_agent.online_research.socket.getaddrinfo',return_value=[(0,0,0,0,(ip,443))]):
                with self.assertRaises(ValueError):public_addresses('example.com')

    def test_redirect_dns_is_revalidated_and_target_is_pinned(self):
        response=MagicMock();response.status=302;response.getheader.side_effect=lambda key,*a:'https://inside.example.com/a' if key=='Location' else None
        connection=MagicMock();connection.getresponse.return_value=response
        addresses=[[(0,0,0,0,('8.8.8.8',443))],[(0,0,0,0,('127.0.0.1',443))]]
        with patch('embedded_agent.online_research.socket.getaddrinfo',side_effect=addresses),patch('embedded_agent.online_research.http.client.HTTPSConnection',return_value=connection) as factory:
            with self.assertRaises(ValueError):fetch_public('https://example.com/a',['example.com'])
            self.assertEqual(factory.call_count,1);self.assertEqual(connection.request.call_count,1)
        self.assertTrue(callable(connection._create_connection))

    def test_pdf_physical_page_index_is_preserved(self):
        import io
        from pypdf import PdfWriter
        from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
        writer=PdfWriter()
        for number in (1,2):
            page=writer.add_blank_page(width=400,height=400)
            font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
            page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):font})})
            stream=DecodedStreamObject();stream.set_data(('BT /F1 10 Tf 10 300 Td (NEWCHIP123 voltage page '+str(number)+' '+('manufacturer conditions '*8)+') Tj ET').encode())
            page[NameObject('/Contents')]=stream
        raw=io.BytesIO();writer.write(raw);self.enable()
        with patch('embedded_agent.online_research.fetch_public',return_value={'url':'https://example.com/data.pdf','mime':'application/pdf','raw':raw.getvalue()}):
            result=self.web.import_url(self.pid,'https://example.com/data.pdf')
        self.assertEqual(result['status'],'imported',result)
        self.assertEqual(result['pages'],2)
        page=self.library.page(result['document_id'],2);self.assertIn('page 2',page['text'])
        self.assertIn('p.2',page['citation'])

if __name__=='__main__':unittest.main()
