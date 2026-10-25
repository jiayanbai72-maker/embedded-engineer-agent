"""Read-only live API smoke check with the visually reviewed TMP117 reference record."""
import json
from pathlib import Path
import sys
import urllib.request
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from embedded_agent.application import Application
from embedded_agent.selection import evaluate_selection

def main():
    root=Path(__file__).resolve().parents[1]
    with urllib.request.urlopen('http://127.0.0.1:8765/knowledge/status',timeout=5) as response:
        status=json.load(response)
    with urllib.request.urlopen('http://127.0.0.1:8765/knowledge/parameters',timeout=5) as response:
        records=json.load(response)['parameters']
    parameter=next(p for p in records if p.get('valid') and p.get('parameter')=='input_max_v' and p.get('document_id')=='DOC-afe974873c80a7a4')
    app=Application(root)
    matches=app.tools.execute('documents.search',{'query':'SU21T','limit':2})
    proposal={'checks':[{'id':'REFERENCE-ONLY','kind':'voltage',
       'inputs':{'input_min_v':1.8,'input_max_v':5.5,'output_min_v':3.3,'output_max_v':3.3},
       'parameter_bindings':{'input_max_v':{'parameter_id':parameter['id'],'model':parameter['model'],'conditions':parameter['conditions']}}}]}
    report=evaluate_selection(proposal,app.parameters.get)
    assert report['status']=='needs_evidence'
    assert len(report['checks'][0]['resolved_evidence'])==1
    proposal['checks'][0]['inputs']['input_max_v']=6
    mismatched=evaluate_selection(proposal,app.parameters.get)
    assert any(e['field']=='input_max_v' for e in mismatched['checks'][0]['binding_errors'])
    assert matches['status']=='passed' and matches['matches']
    output={'scope':'Reference-only provenance smoke check; not a robot selection or electrical validation',
       'index':status,'cross_chip_search':matches,'partial_reference_check':report,'mismatched_input_check':mismatched}
    path=root/'runtime/knowledge/qa/retrieval-smoke.json'; path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'documents':status['documents'],'chunks':status['chunks'],'source_page':parameter['page'],
       'real_parameter_resolved':True,'unreviewed_inputs_blocked':True,'mismatched_value_blocked':True,'SU21T_results':len(matches['matches'])},ensure_ascii=False))

if __name__=='__main__': main()
