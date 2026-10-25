"""Read-only project intake. No model, build, or hardware execution is performed."""
import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
import xml.etree.ElementTree as ET


def inspect(root):
    root = root.resolve(strict=True)
    files = sorted(p for p in root.rglob('*') if p.is_file())
    inventory = []
    projects = []
    for p in files:
        with p.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        inventory.append({
            'path': p.relative_to(root).as_posix(),
            'size_bytes': p.stat().st_size,
            'sha256': digest,
        })
        if p.suffix.lower() not in ('.uvprojx', '.uvproj'):
            continue
        entry = {'path': p.relative_to(root).as_posix(), 'targets': []}
        try:
            tree = ET.parse(p)
            for target in tree.findall('.//Target'):
                refs = []
                for node in target.findall('.//FilePath'):
                    raw = node.text or ''
                    resolved = (p.parent / raw.replace('\\', '/')).resolve()
                    refs.append({'path': raw, 'exists': resolved.is_file(),
                                 'within_input_root': resolved.is_relative_to(root)})
                entry['targets'].append({
                    'name': target.findtext('TargetName'),
                    'configured_device': target.findtext('.//Device'),
                    'compiler': target.findtext('.//pCCUsed'),
                    'cpu_configuration': target.findtext('.//Cpu'),
                    'file_references': refs,
                    'missing_file_count': sum(not r['exists'] for r in refs),
                })
        except (ET.ParseError, OSError) as exc:
            entry['parse_error'] = str(exc)
        projects.append(entry)
    return {
        'schema_version': 1,
        'input_root': str(root),
        'file_count': len(files),
        'extensions': dict(sorted(Counter(p.suffix.lower() or '[none]' for p in files).items())),
        'projects': projects,
        'inventory': inventory,
        'verification': {'intake': 'completed', 'fresh_build': 'not_run',
                         'hardware': 'not_run'},
        'limitations': ['Configured device is not proof of physical device identity.',
                       'Existing binaries and logs are historical evidence only.',
                       'Only Keil project metadata is currently parsed.'],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    source = args.input.resolve(strict=True)
    if not source.is_dir():
        parser.error('input must be a directory')
    output = args.output.resolve()
    if output.is_relative_to(source):
        parser.error('output must be outside input to keep intake read-only and reproducible')
    result = inspect(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'files': result['file_count'], 'projects': len(result['projects']),
                      'output': str(output)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
