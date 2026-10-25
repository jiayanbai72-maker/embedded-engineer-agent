"""Export a clean build context; never packages runtime, credentials or user projects."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
from zipfile import ZipFile, ZIP_DEFLATED


def package(root, output, include_official=False):
    root, output = Path(root).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    context = output / 'embedded-agent-agentarts-source'
    if context.exists(): raise ValueError('输出目录已存在，请指定新的输出目录，避免覆盖已配置内容')
    context.mkdir()
    for name in ('src', 'deployments', 'docs'):
        for file in (root / name).rglob('*'):
            if not file.is_file() or '__pycache__' in file.parts or file.suffix == '.pyc' or file.name.startswith('.env') or 'local-config' in file.name: continue
            target = context / file.relative_to(root); target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(file, target)
    (context / 'knowledge').mkdir()
    shutil.copyfile(root / 'knowledge/index.json', context / 'knowledge/index.json')
    shutil.copyfile(root / 'pyproject.toml', context / 'pyproject.toml')
    if include_official:
        shutil.copytree(root / 'knowledge/official', context / 'knowledge/official')
    manifest = {p.relative_to(context).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in context.rglob('*') if p.is_file()}
    (context / 'SOURCE-MANIFEST.json').write_text(json.dumps({'mode': 'source_not_container_image', 'official_documents_included': include_official,
                                                            'files': manifest}, ensure_ascii=False, indent=2), encoding='utf-8')
    archive = output / 'embedded-agent-agentarts-source.zip'
    with ZipFile(archive, 'w', ZIP_DEFLATED) as bundle:
        for file in context.rglob('*'):
            if file.is_file(): bundle.write(file, file.relative_to(context).as_posix())
    return {'source_directory': str(context), 'source_zip': str(archive), 'files': len(manifest),
            'uploadable_to_swr': False, 'next': '在ARM64 Docker环境构建后docker save导出镜像tar'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[2] / 'runtime/agentarts-release')
    parser.add_argument('--include-official', action='store_true')
    args = parser.parse_args()
    print(json.dumps(package(Path(__file__).resolve().parents[2], args.output, args.include_official), ensure_ascii=False))
