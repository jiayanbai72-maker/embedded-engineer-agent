"""Allowlisted clean source distribution; never walks runtime or credentials."""
import hashlib
import json
from pathlib import Path
import re
from zipfile import ZipFile,ZIP_DEFLATED

ROOT=Path(__file__).resolve().parents[1]
TOOLS=('verify_agent_closed_loop.py','run_expanded_tests.py','expanded_state_cases.py',
       'run_new_scenarios.py','run_evidence_transfer.py','run_hard_c_cases.py',
       'run_hard_requirements.py','compare_prompt_cost.py','build_online_source.py')

def build(output):
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    files=[]
    for directory,extensions in (('src',{'.py','.js','.css','.html'}),('tests',{'.py'}),
                                 ('examples',{'.py','.json','.c','.h'}),('docs',{'.md'}),
                                 ('deploy',{'.md','.yml','.example',''})):
        for p in (ROOT/directory).rglob('*'):
            if p.is_file() and not p.is_symlink() and p.suffix in extensions and '__pycache__' not in p.parts and p.name!='.env':files.append(p)
    for name in ('README.md','ONLINE-START-HERE.md','pyproject.toml','.gitignore','.dockerignore','Dockerfile.online','.env.example','启动工作台.ps1','start-workbench.cmd','knowledge/index.json'):
        files.append(ROOT/name)
    files.extend(ROOT/'tools'/name for name in TOOLS)
    records=[]
    with ZipFile(output,'w',ZIP_DEFLATED) as archive:
        for p in sorted(set(files)):
            if not p.resolve().is_relative_to(ROOT) or not p.is_file():raise ValueError('Missing or unsafe allowlisted source file')
            relative=p.relative_to(ROOT).as_posix();raw=p.read_bytes()
            if re.search(rb'sk-[A-Za-z0-9]{24,}',raw):raise ValueError('Potential credential in source; manual review required: '+relative)
            archive.writestr('embedded-workbench-online/'+relative,raw)
            records.append({'path':relative,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
        manifest={'files':records,'excluded':['runtime','credentials','usage databases','personal projects and conversations','downloaded vendor documents','third-party compiler installations'],
                  'scope':'Source delivery only; Docker runtime and public deployment not verified'}
        archive.writestr('embedded-workbench-online/SOURCE-MANIFEST.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    return {'archive':str(output),'files':len(records),'bytes':output.stat().st_size,'sha256':hashlib.sha256(output.read_bytes()).hexdigest()}

if __name__=='__main__':
    target=ROOT.parent/'发布包'/'embedded-workbench-online-source-20261026.zip'
    print(json.dumps(build(target),ensure_ascii=False))
