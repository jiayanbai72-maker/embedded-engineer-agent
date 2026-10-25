"""MCU compile-only port and ARMCC adapter. No linker, flash, or device execution."""
import base64
import hashlib
import os
from pathlib import Path
import re
import subprocess
from typing import Protocol
from uuid import uuid4


class MCUCompiler(Protocol):
    def compile(self, files: dict[str, str], cpu: str, workspace: Path) -> dict: ...


def validate_sources(files, cpu):
    if cpu not in ('Cortex-M0', 'Cortex-M0plus', 'Cortex-M3', 'Cortex-M4'):
        raise ValueError('当前未支持该处理器配置')
    if not isinstance(files, dict) or not files or len(files) > 20:
        raise ValueError('需要1至20个C源文件或头文件')
    for name, body in files.items():
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*\.(c|h)', name):
            raise ValueError('仅接受单层C源码和头文件名')
        if not isinstance(body, str) or not body.strip() or len(body) > 100_000:
            raise ValueError('源码内容不正确')
    if not any(name.endswith('.c') for name in files):
        raise ValueError('需要C源文件')


class ArmccCompiler:
    def __init__(self, executable):
        self.executable = Path(executable)

    def compile(self, files, cpu, workspace):
        validate_sources(files, cpu)
        result = {'status': 'failed', 'scope': 'mcu_object_compilation', 'cpu': cpu,
                  'firmware_link': 'not_run', 'hardware': 'not_run', 'commands': [], 'objects': {},
                  'source_hashes': {n: hashlib.sha256(b.encode()).hexdigest() for n, b in files.items()}}
        if not self.executable.is_absolute() or not self.executable.is_file():
            return dict(result, status='unsupported', reason='本地未配置可用ARMCC编译器')
        workspace.mkdir(parents=True, exist_ok=True)
        logs = []
        try:
            version = subprocess.run([str(self.executable), '--vsn'], capture_output=True, timeout=10)
            result['tool_version'] = (version.stdout + version.stderr).decode('utf-8', errors='replace')
            if version.returncode != 0:
                return dict(result, reason='编译器版本检测失败', log=result['tool_version'])
            for name, body in files.items():
                (workspace / name).write_text(body, encoding='utf-8')
            for name in sorted(n for n in files if n.endswith('.c')):
                obj = Path(name).with_suffix('.o').name
                command = [str(self.executable), '--cpu=' + cpu, '--c99', '-c', name, '-o', obj]
                run = subprocess.run(command, cwd=workspace, capture_output=True, timeout=20)
                logs.append((run.stdout + run.stderr).decode('utf-8', errors='replace'))
                result['commands'].append({'argv': command, 'returncode': run.returncode})
                if run.returncode != 0 or not (workspace / obj).is_file():
                    return dict(result, reason='编译失败或未生成目标文件', log='\n'.join(logs)[-50000:])
                raw = (workspace / obj).read_bytes()
                if len(raw) > 1_000_000:
                    return dict(result, reason='目标文件过大')
                result['objects'][obj] = {'sha256': hashlib.sha256(raw).hexdigest(), 'size_bytes': len(raw),
                                           'base64': base64.b64encode(raw).decode('ascii')}
            result['status'] = 'passed'
            result['log'] = '\n'.join(logs)[-50000:]
            return result
        except subprocess.TimeoutExpired:
            return dict(result, reason='编译工具超时')
        except OSError:
            return dict(result, reason='本地工具或文件访问失败')


def compile_project(root, project):
    impl = project.artifacts['mcu_implementation']
    path = os.environ.get('EMBEDDED_AGENT_ARMCC', 'C:/Keil_v5/ARM/ARMCC/bin/armcc.exe')
    directory = root / 'runtime' / 'mcu-runs' / project.id / str(uuid4())
    return ArmccCompiler(path).compile(impl['files'], impl['cpu'], directory)
