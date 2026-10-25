"""Trusted local uVision project copies, bounded edits and real batch builds."""
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from uuid import uuid4


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def inside(root, value):
    path = (root / str(value).replace('\\', '/')).resolve()
    if not path.is_relative_to(root.resolve()): raise ValueError('工程路径越界，不支持工程目录外的依赖或输出')
    return path


def inspect_project(file, target=None):
    file = Path(file).resolve()
    if file.suffix.lower() not in ('.uvprojx', '.uvproj') or not file.is_file(): raise ValueError('需要存在的 Keil XML 工程文件')
    raw = file.read_bytes()
    if len(raw) > 2_000_000 or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper(): raise ValueError('工程 XML 超出支持范围')
    try: tree = ET.fromstring(raw)
    except ET.ParseError: raise ValueError('工程 XML 无法解析') from None
    for node in tree.iter():
        if node.tag.startswith('RunUserProg') and (node.text or '').strip() not in ('', '0'):
            raise ValueError('当前不支持启用自定义构建命令的工程')
        if node.tag in ('FilePath', 'ScatterFile', 'OutputDirectory', 'ListingPath', 'OutputName') and (node.text or '').strip():
            inside(file.parent, node.text.strip())
        if node.tag == 'IncludePath' and node.text:
            for part in node.text.split(';'):
                if part.strip(): inside(file.parent, part.strip())
    targets = tree.findall('./Targets/Target')
    names = [t.findtext('TargetName') for t in targets]
    if not names or any(not name for name in names): raise ValueError('工程没有有效 Target')
    if target is None:
        if len(names) != 1: raise ValueError('多 Target 工程需要明确选择目标')
        target = names[0]
    if target not in names: raise ValueError('Target 不存在')
    chosen = targets[names.index(target)]
    return {'target': target, 'targets': names, 'device': chosen.findtext('.//Device'),
            'project_sha256': sha(file), 'files': [n.text for n in chosen.findall('.//FilePath') if n.text]}


def import_project(root, project_id, file, target=None):
    source = Path(file).resolve()
    # The user-facing import grants access only to this task workspace, never arbitrary disk paths.
    if not source.is_relative_to(root.resolve().parents[1]): raise ValueError('仅支持当前工作空间内的工程')
    info = inspect_project(source, target)
    files = list(source.parent.rglob('*'))
    if len(files) > 4000 or any(p.is_symlink() or p.is_junction() for p in files): raise ValueError('工程包含链接或文件数过多')
    if sum(p.stat().st_size for p in files if p.is_file()) > 100_000_000: raise ValueError('工程副本超过100MB')
    folder = root / 'runtime' / 'keil' / project_id / str(uuid4())
    if folder.resolve().is_relative_to(source.parent): raise ValueError('导入目录包含运行存储目录，请将工程放在独立子目录中')
    shutil.copytree(source.parent, folder)
    editable = {}
    for p in folder.rglob('*'):
        if p.is_file() and p.suffix.lower() in ('.c', '.h', '.cpp', '.s'):
            if p.stat().st_size <= 200_000: editable[p.relative_to(folder).as_posix()] = sha(p)
    return dict(info, workspace=str(folder.relative_to(root)), project_file=source.name,
                original=str(source), editable=editable, trusted_local=True, hardware='not_run')


def workspace(root, imported):
    folder = inside(root, imported['workspace'])
    if not folder.is_relative_to((root / 'runtime' / 'keil').resolve()): raise ValueError('不是受管理的 Keil 副本')
    file = inside(folder, imported['project_file'])
    if sha(file) != imported['project_sha256']: raise ValueError('工程配置已变化，请重新导入')
    return folder, file


def read_source(root, imported, name):
    folder, _ = workspace(root, imported)
    if name not in imported['editable']: raise ValueError('源码不在导入时的可编辑清单')
    file = inside(folder, name)
    raw = file.read_bytes()
    try: content, encoding = raw.decode('utf-8-sig'), 'utf-8-sig' if raw.startswith(b'\xef\xbb\xbf') else 'utf-8'
    except UnicodeDecodeError:
        try: content, encoding = raw.decode('gb18030'), 'gb18030'
        except UnicodeDecodeError: raise ValueError('源码编码不支持') from None
    return {'file': name, 'sha256': sha(file), 'content': content, 'encoding': encoding}


def edit_source(root, imported, changes, rationale):
    if not isinstance(rationale, str) or not rationale.strip() or not isinstance(changes, list) or not 1 <= len(changes) <= 10:
        raise ValueError('修改需要依据和1至10项源码变更')
    prepared, seen = [], set()
    for change in changes:
        name = change.get('file'); current = read_source(root, imported, name)
        if name in seen or current['sha256'] != change.get('sha256'): raise ValueError('源码已变化或重复修改，请重新读取')
        content = change.get('content')
        if not isinstance(content, str) or not 0 < len(content) <= 200_000: raise ValueError('新源码为空或过大')
        seen.add(name)
        try: encoded = content.encode(current['encoding'])
        except UnicodeEncodeError: raise ValueError('修改内容无法按原源码编码保存') from None
        prepared.append((inside(root / imported['workspace'], name), encoded, current))
    # All files are validated before any write. Controller stops uncertain interruptions.
    history = []
    for file, raw, old in prepared:
        temporary = file.with_suffix(file.suffix + '.agent-tmp'); temporary.write_bytes(raw); temporary.replace(file)
        history.append({'file': old['file'], 'before': old, 'after_sha256': sha(file)})
    return {'changes': history, 'rationale': rationale}


def diagnostics(log):
    result = []
    patterns = [r'^\s*(.+?)\((\d+)\)\s*:\s*(fatal error|error|warning|note)\s*:?\s*(.*)$',
                r'^\s*(.+?):(\d+)(?::(\d+))?:\s*(fatal error|error|warning|note):\s*(.*)$']
    for line in log.splitlines():
        m = re.match(patterns[0], line, re.I)
        if m: file, number, severity, message = m.groups(); column = None
        else:
            m = re.match(patterns[1], line, re.I)
            if not m: continue
            file, number, column, severity, message = m.groups()
        result.append({'file': file.strip('"'), 'line': int(number), 'column': int(column) if column else None,
                       'severity': severity.lower(), 'message': message, 'raw': line})
    return result


def build(root, imported, timeout=120):
    folder, file = workspace(root, imported)
    inspect_project(file, imported['target'])
    executable = Path(os.environ.get('EMBEDDED_AGENT_UVISION', r'C:\Keil_v5\UV4\UV4.exe'))
    if not executable.is_absolute() or not executable.is_file(): return {'status': 'unsupported', 'reason': '本机未配置 UV4.exe', 'hardware': 'not_run'}
    log_file = folder / ('agent-build-' + str(uuid4()) + '.log')
    command = [str(executable), '-r', str(file), '-t', imported['target'], '-o', str(log_file)]
    try:
        process = subprocess.run(command, cwd=folder, capture_output=True, timeout=timeout,
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except subprocess.TimeoutExpired: return {'status': 'failed', 'reason': 'Keil 构建超时，停止自动重试；需核实子进程状态', 'hardware': 'not_run', 'uncertain': True}
    except OSError: return {'status': 'failed', 'reason': '无法启动 UV4.exe，请检查本机执行权限和配置', 'hardware': 'not_run'}
    raw = log_file.read_bytes() if log_file.is_file() else b''
    log = raw.decode('utf-8-sig', errors='replace')
    if '\ufffd' in log: log = raw.decode('gb18030', errors='replace')
    parsed = diagnostics(log)
    for diagnostic in parsed:
        try:
            source = inside(folder, diagnostic['file']).relative_to(folder).as_posix()
            diagnostic['source_file'] = source if source in imported['editable'] else None
        except ValueError:
            diagnostic['source_file'] = None
    success = process.returncode in (0, 1) and bool(log.strip()) and not any(d['severity'] in ('error', 'fatal error') for d in parsed)
    # A zero exit code alone is insufficient when uVision returns before a build or reports a link failure.
    summary = re.search(r'(\d+)\s+Error\(s\).*?(\d+)\s+Warning\(s\)', log, re.I)
    success = success and summary is not None and int(summary[1]) == 0
    return {'status': 'passed' if success else 'failed', 'exit_code': process.returncode, 'command': command,
            'target': imported['target'], 'log': log[-200_000:], 'log_sha256': hashlib.sha256(raw).hexdigest(),
            'diagnostics': parsed, 'hardware': 'not_run', 'scope': 'keil_project_build',
            'source_hashes': {name: sha(inside(folder, name)) for name in imported['editable']}}
