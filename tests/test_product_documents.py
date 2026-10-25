import copy
import io
import json
import unittest
from unittest.mock import MagicMock,patch
from zipfile import ZipFile
import test_control
from embedded_agent.product_documents import SECTIONS,validate,exports,fingerprint,wiring_appendix


def answer():
    return {'sections':[{'id':key,'body':'这是来自现有工程记录的测试说明。候选方案仍待电气与硬件验证，不代表实机通过。'*2,'source_refs':['selected_plan']} for key,_ in SECTIONS],
      'bom':[{'name':'元件'+str(i),'model':'待定','specification':'待选型','purpose':'演练','quantity':None,'quantity_note':'待定','alternative':'未验证','open_items':'待核实','source_refs':['selected_plan']} for i in range(5)]}


class ProductDocumentTests(unittest.TestCase):
    setUp=test_control.ControlTests.setUp
    tearDown=test_control.ControlTests.tearDown
    prepared=test_control.ControlTests.prepared

    def test_wiring_appendix_preserves_agent_signals_without_axis_inference(self):
        report={'status':'passed','model':'NEWMCU','package':'TEST32','mappings':[
            {'pin':'P8','af':'AF7','signal':'TIM9_CH4','physical_pin':17,'fact_id':'FACT-1','package_fact_id':'FACT-2'}],
            'voice_pins':[],'sources':[]}
        files=wiring_appendix(report)
        manifest=json.loads(files['engineering-draft/interfaces/pin-bindings.json'])
        self.assertEqual(manifest['mappings'][0]['signal'],'TIM9_CH4')
        self.assertEqual(manifest['mappings'][0]['physical_pin'],17)
        self.assertNotIn('axis',manifest['mappings'][0])
        self.assertFalse(manifest['board_driver_implemented'])
        self.assertIn('不等于',files['engineering-draft/interfaces/PIN_ASSIGNMENT.md'])

    def test_incomplete_wiring_stays_incomplete_and_svg_escapes_text(self):
        report={'status':'needs_evidence','model':'<script>alert(1)</script>','package':'unknown','mappings':[
            {'pin':'P1','af':None,'signal':None,'physical_pin':None}], 'voice_pins':[]}
        files=wiring_appendix(report)
        self.assertNotIn('<script>',files['product-design/候选引脚映射.svg'])
        self.assertIn('仍有缺口',files['engineering-draft/interfaces/PIN_ASSIGNMENT.md'])
        data=json.loads(files['engineering-draft/interfaces/pin-bindings.json'])
        self.assertIsNone(data['mappings'][0]['physical_pin'])

    def test_invalid_draft_is_repaired_once_and_cached_without_further_spend(self):
        from embedded_agent.product_documents import generate
        old=self.prepared();project=self.service.app.store.load(old['project_id'])
        model=MagicMock();model.generate.side_effect=[{'sections':[]},answer()]
        generated=generate(self.service,project,model)
        self.assertEqual(model.generate.call_count,2)
        self.assertEqual(generated['author'],'configured_agent')
        generate(self.service,project,model)
        self.assertEqual(model.generate.call_count,2)

    def test_document_role_uses_document_contract_not_action_contract(self):
        from embedded_agent.local_model import BudgetModel,Budget
        model=BudgetModel('deepseek-flash','fixture',Budget(self.root/'usage.sqlite3'))
        body={'usage':{'prompt_tokens':100,'completion_tokens':20},'choices':[{'finish_reason':'stop','message':{'content':'{}'}}]}
        with patch('embedded_agent.local_model.build_opener') as op:
            op.return_value.open.return_value.__enter__.return_value.read.return_value=json.dumps(body).encode()
            model.generate(role='product_document_writer',instruction='document',context={})
            payload=json.loads(op.return_value.open.call_args.args[0].data)
        prefix=payload['messages'][1]['content']
        self.assertIn('document_contract',prefix);self.assertNotIn('action_contracts',prefix)

    def test_invalid_structure_quantity_and_sources_rejected(self):
        for mutate in (lambda d:d['sections'].pop(),lambda d:d['bom'][0].update(quantity=True),lambda d:d['bom'][0].update(source_refs=['imaginary'])):
            data=answer();mutate(data)
            with self.assertRaises(ValueError):validate(data,['selected_plan'])

    def test_export_escapes_html_and_neutralizes_csv_formulas_and_prices(self):
        data=answer();data['bom'][0].update(name='=HYPERLINK("bad")',unit_price_cny=5,subtotal_cny=5)
        data['sections'][0]['body']+='<script>bad()</script>'
        document=validate(data,['selected_plan'])
        document.update(source_revision=1,source_sha256='hash')
        files=exports(document)
        self.assertIsNone(document['bom'][0]['unit_price_cny'])
        self.assertNotIn('<script>',files['product-design/产品详细设计与制作说明.html'])
        self.assertIn("'=HYPERLINK",files['product-design/元件清单.csv'])
        self.assertIn('待核价',files['product-design/元件清单.csv'])

    def test_product_documents_are_generated_once_and_preserve_implementation(self):
        old=self.prepared();project=self.service.app.store.load(old['project_id'])
        before=copy.deepcopy(project.artifacts['selected_plan']);model=MagicMock();model.generate.return_value=answer()
        with patch('embedded_agent.local_model.LocalSettings.model',return_value=model):
            result=self.service.update(project.id,project.revision,'product_documents',{})
            again=self.service.update(project.id,result['revision'],'product_documents',{})
        model.generate.assert_called_once();self.assertEqual(again['revision'],result['revision'])
        self.assertEqual(result['artifacts']['selected_plan'],before)
        project=self.service.app.store.load(project.id)
        with ZipFile(io.BytesIO(self.service.archive(project))) as archive:
            self.assertIn('product-design/元件清单.csv',archive.namelist())
        project.artifacts['selected_plan']['name']='changed'
        with ZipFile(io.BytesIO(self.service.archive(project))) as archive:
            self.assertNotIn('product-design/元件清单.csv',archive.namelist())
            self.assertIn('product-design/文档已过期.md',archive.namelist())

    def test_delivered_archive_is_rehashed_and_download_remains_valid(self):
        old=self.prepared();project=self.service.app.store.load(old['project_id'])
        project.status='documents_delivered';project.artifacts['delivery']={'sha256':'old','kind':'documentation'};self.service.app.store.save(project)
        model=MagicMock();model.generate.return_value=answer()
        with patch('embedded_agent.local_model.LocalSettings.model',return_value=model):
            result=self.service.update(project.id,project.revision,'product_documents',{})
        archive=self.service.download(project.id)
        self.assertEqual(result['status'],'documents_delivered')
        with ZipFile(io.BytesIO(archive)) as z:self.assertIn('product-design/产品详细设计与制作说明.html',z.namelist())
