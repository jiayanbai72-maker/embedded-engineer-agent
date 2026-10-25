import json
from pathlib import Path
import collect_general_knowledge as g

r=g.ROOT
m=json.loads((r/'knowledge/official/general-v1-extension/manifest.json').read_text(encoding='utf-8'))
for s in m['sources']:
    if s['url'].endswith('/sx1262') and s['status']=='downloaded':
        parser=g.base.Links(); parser.feed((r/s['local_path']).read_text(encoding='utf-8'))
        print('SEMTECH',*[x for x in parser.links if any(w in x.lower() for w in ('pdf','datasheet','sx126'))],sep='\n')
for folder in ('general-v1','general-v1-extension'):
    m=json.loads((r/'knowledge/official'/folder/'manifest.json').read_text(encoding='utf-8'))
    for s in m['sources']:
        if s.get('extraction_status')=='failed': print('EXTRACTION_ERROR',s['local_path'],s.get('extraction_error'))
