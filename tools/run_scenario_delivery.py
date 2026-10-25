"""Replay one isolated analysis result through simulated user gates and live docs."""
import argparse
import io
import json
from pathlib import Path
import sys
from unittest.mock import patch
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
from test_architecture import ArchitectureTests
from embedded_agent.service import EngineeringService
from embedded_agent.local_model import LocalSettings
from run_expanded_tests import Metered


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true');parser.add_argument('--source',required=True);args=parser.parse_args()
    if not args.live:raise SystemExit('Explicit --live required')
    source=Path(args.source).resolve();original=json.loads(source.read_text(encoding='utf-8'))
    if not original.get('passed'):raise ValueError('Analysis fixture must have passed')
    fixture=ArchitectureTests();fixture.setUp();folder=source.parent/(original['case']+'-delivery');folder.mkdir(exist_ok=True)
    model=Metered(LocalSettings(ROOT).model());before=model.budget.status()['accounted_cny']
    report={'case':original['case'],'gates':'Test driver simulates requirement confirmation and first candidate selection; not autonomous model approval.','scope':'live_model_design_document_and_bom_only_no_firmware_or_hardware'}
    try:
        from embedded_agent.domain import Project
        s=EngineeringService(fixture.root);p={k:v for k,v in original['project'].items() if k in Project.__dataclass_fields__};pid=p['id']
        (s.app.store.root/(pid+'.json')).write_text(json.dumps(p,ensure_ascii=False),encoding='utf-8')
        p=s.update(pid,p['revision'],'confirm',{'confirmed':True})
        p=s.update(pid,p['revision'],'select',{'candidate_id':p['artifacts']['comparison']['candidates'][0]['id']})
        with patch('embedded_agent.local_model.LocalSettings.model',return_value=model):p=s.update(pid,p['revision'],'product_documents',{})
        p=s.update(pid,p['revision'],'execute',{})
        archive=s.download(pid);(folder/'delivery.zip').write_bytes(archive)
        doc=p['artifacts']['product_documents'];text=json.dumps(doc,ensure_ascii=False)
        unrelated=[word for word in ('纸盒机器人','SU-21T','SG90','robot_app','voice_uart') if word in text]
        with ZipFile(io.BytesIO(archive)) as z:
            names=z.namelist()
            for name in names:
                if name.startswith('product-design/'):
                    target=folder/Path(name).name;target.write_bytes(z.read(name))
        report.update(passed=not unrelated and len(doc['sections'])==12 and len(doc['bom'])>=5 and all(r['unit_price_cny'] is None for r in doc['bom']),
                      chapters=len(doc['sections']),bom_rows=len(doc['bom']),unrelated_robot_content=unrelated,hardware=p['verification']['hardware'])
        (folder/'project.json').write_text(json.dumps(p,ensure_ascii=False,indent=2),encoding='utf-8')
    except Exception as exc:report.update(passed=False,error=str(exc)[:600],error_type=type(exc).__name__)
    finally:
        for raw in (fixture.root/'runtime/product-documents').rglob('agent-*.json'):
            (folder/raw.name).write_bytes(raw.read_bytes())
        fixture.tearDown()
    report['accounted_cost_cny']=model.budget.status()['accounted_cny']-before
    report['calls']=model.calls
    (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
