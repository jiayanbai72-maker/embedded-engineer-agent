"""Host behavioral-prototype adapter. Not an MCU firmware toolchain."""
import hashlib
from pathlib import Path
import subprocess
import sys


def validate_files(files):
    if not isinstance(files, dict) or not files or len(files) > 20:
        raise ValueError('需要1至20个主机原型文件')
    for name, body in files.items():
        if not isinstance(name, str) or Path(name).name != name or '/' in name or '\\' in name or not name.endswith('.py'):
            raise ValueError('仅接受项目内单层 Python 文件名')
        if not isinstance(body, str) or not body.strip() or len(body) > 100_000:
            raise ValueError('文件内容无效')
    if not any(name.startswith('test_') for name in files):
        raise ValueError('需要测试文件')


def run_host(root, project, testing=False):
    files = project.artifacts['implementation']['files']
    validate_files(files)
    directory = root / 'runtime' / 'host-runs' / project.id / str(project.revision)
    directory.mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        (directory / name).write_text(body, encoding='utf-8')
    if testing:
        command = [sys.executable, '-X', 'utf8', '-m', 'unittest', 'discover', '-s', '.', '-p', 'test_*.py', '-v']
    else:
        command = [sys.executable, '-X', 'utf8', '-m', 'py_compile'] + sorted(files)
    try:
        result = subprocess.run(command, cwd=directory, capture_output=True, text=True, encoding='utf-8', timeout=20)
        log = result.stdout + result.stderr
        passed = result.returncode == 0 and (not testing or ('Ran ' in log and '\nOK' in log and 'Ran 0 tests' not in log))
        return {'status': 'passed' if passed else 'failed', 'execution_mode': 'host_behavioral_prototype',
                'command': command, 'returncode': result.returncode, 'log': log[-50000:],
                'source_hashes': {n: hashlib.sha256(b.encode()).hexdigest() for n, b in files.items()},
                'tool_version': sys.version, 'firmware_build': 'not_run', 'hardware': 'not_run'}
    except subprocess.TimeoutExpired:
        return {'status': 'failed', 'execution_mode': 'host_behavioral_prototype', 'log': '执行超时',
                'firmware_build': 'not_run', 'hardware': 'not_run'}
