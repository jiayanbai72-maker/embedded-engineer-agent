"""Prepare an allowlisted public source tree; never reads private runtime data."""

import os
# Public helper: configure EMBEDDED_INPUT_PATH_1, EMBEDDED_INPUT_PATH_2 before use.
import ast
import hashlib
import json
from pathlib import Path
import re
import sys
from zipfile import ZipFile, ZIP_DEFLATED

ROOT=Path(__file__).resolve().parents[1]
UUID=re.compile(r'''(['"])([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})\1''',re.I)
SECRETS={
 'provider_token':rb'(?:sk-[A-Za-z0-9]{24,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})',
 'private_key':rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
}

def sanitize_helper(body):
    ids={};paths={}
    def project(match):
        value=match[2]
        if value not in ids:ids[value]='EMBEDDED_PROJECT_ID_'+str(len(ids)+1)
        return 'os.environ['+repr(ids[value])+']'
    body=UUID.sub(project,body)
    # Replace complete personal-machine path literals, not arbitrary Python code.
    replacements=[]
    tree=ast.parse(body);lines=body.splitlines(keepends=True)
    for node in ast.walk(tree):
        if isinstance(node,ast.Constant) and isinstance(node.value,str) and re.match(r'^[A-Za-z]:[\\/]',node.value) and ('华为ICT' in node.value or re.search(r'[/\\]Users[/\\]bjy',node.value,re.I)):
            if node.lineno!=node.end_lineno:raise ValueError('Review multiline private path')
            key='EMBEDDED_INPUT_PATH_'+str(len(paths)+1);paths[key]=True
            # AST columns count UTF-8 bytes, including Chinese path components.
            line=lines[node.lineno-1].encode('utf-8')
            replacements.append((node.lineno-1,node.col_offset,node.end_col_offset,('os.environ['+repr(key)+']').encode('utf-8')))
    for index,start,end,value in sorted(replacements,reverse=True):
        line=lines[index].encode('utf-8');lines[index]=(line[:start]+value+line[end:]).decode('utf-8')
    body=''.join(lines)
    if ids or paths:
        tree=ast.parse(body);insert=0
        if tree.body and isinstance(tree.body[0],ast.Expr) and isinstance(tree.body[0].value,ast.Constant) and isinstance(tree.body[0].value.value,str):insert=tree.body[0].end_lineno
        while insert<len(body.splitlines()) and body.splitlines()[insert].startswith('from __future__ import '):insert+=1
        lines=body.splitlines(keepends=True)
        keys=list(ids.values())+list(paths)
        lines.insert(insert,'\nimport os\n# Public helper: configure '+', '.join(keys)+' before use.\n')
        body=''.join(lines)
    ast.parse(body)
    return body, list(ids.values())+list(paths)

def prepare(destination):
    destination=Path(destination).resolve()
    if destination.exists():raise ValueError('Release directory already exists; do not overwrite')
    destination.mkdir(parents=True)
    files=[];changes=[]
    for directory,extensions in (('src',{'.py','.js','.css','.html'}),('tests',{'.py'}),
      ('examples',{'.py','.json','.c','.h'}),('tools',{'.py'}),('docs',{'.md'}),
      ('deploy',{'.md','.yml','.example',''}),('deployments',{'.py','.md','.json','.html','.js','.sh','.cmd','', '.dockerignore'}),
      ('.github',{'.yml','.yaml'})):
        for p in (ROOT/directory).rglob('*'):
            if p.is_file() and not p.is_symlink() and p.suffix in extensions and '__pycache__' not in p.parts and p.name not in ('.env','local-config.json','settings.json'):
                files.append((p,p.relative_to(ROOT)))
    for name in ('pyproject.toml','.gitignore','.dockerignore','Dockerfile.online','.env.example','启动工作台.ps1','start-workbench.cmd','ONLINE-START-HERE.md','LICENSE','CONTRIBUTING.md','SECURITY.md','THIRD_PARTY_NOTICES.md','knowledge/index.json','knowledge/seed_cards.json','knowledge/所需知识库清单.md','knowledge/通用资料说明.md'):
        files.append((ROOT/name,Path(name)))
    public_readme=ROOT/'README.public.md'
    files.append((public_readme if public_readme.is_file() else ROOT/'README.md',Path('README.md')))
    for source,relative in sorted(files,key=lambda pair:pair[1].as_posix()):
        if not source.resolve().is_relative_to(ROOT):raise ValueError('Unsafe source path')
        body=source.read_text(encoding='utf-8-sig')
        if relative.parts[0] in ('tools','examples') and relative.suffix=='.py':
            body,keys=sanitize_helper(body)
            if keys:changes.append({'file':relative.as_posix(),'required_environment':keys})
        body=body.replace(os.environ['EMBEDDED_INPUT_PATH_2'],'C:/Users/<user>/').replace(os.environ['EMBEDDED_INPUT_PATH_1'],'C:\\Users\\<user>\\')
        raw=body.encode('utf-8')
        for label,pattern in SECRETS.items():
            if re.search(pattern,raw):raise ValueError('Potential secret in '+relative.as_posix()+' ('+label+')')
        target=destination/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
    manifest=[]
    for p in sorted(destination.rglob('*')):
        if p.is_file():manifest.append({'path':p.relative_to(destination).as_posix(),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
    report={'files':manifest,'sanitized_helpers':changes,'excluded':['runtime','credentials','conversations','personal projects','cases/intake inventories','vendor downloads','compiler binaries','bytecode','original git history'],
            'license':'MIT','scope':'dual-mode preview source; hardware and public deployment remain unverified'}
    (destination/'SOURCE-MANIFEST.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return {'directory':str(destination),'files':len(manifest)+1,'sanitized_helpers':len(changes),'credential_hits':0}

if __name__=='__main__':
    target=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT.parent/'开源发布'/'embedded-engineer-agent'
    print(json.dumps(prepare(target),ensure_ascii=False))
