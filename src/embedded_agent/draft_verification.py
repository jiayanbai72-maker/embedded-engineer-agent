"""Execute real local tools on a source-bound draft; no model call here."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4
from .mcu import ArmccCompiler


def source_hash(files):
    return hashlib.sha256(json.dumps({n:b for n,b in files.items() if n.endswith(('.c','.h'))},sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def run_local(command, **kwargs):
    # Child test assertions must not wait for Windows crash-report UI.
    if os.name!='nt':return subprocess.run(command,**kwargs)
    import ctypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    previous=kernel.GetErrorMode()
    kernel.SetErrorMode(previous | 0x0001 | 0x0002)
    try:return subprocess.run(command,**kwargs)
    finally:kernel.SetErrorMode(previous)


def verify(root, files, cpu):
    from .mcu import validate_sources
    sources={n:b for n,b in files.items() if n.endswith(('.c','.h'))}
    validate_sources(sources,cpu)
    tests=[n for n in sources if n.startswith('test_') and n.endswith('.c')]
    if len(tests)!=1: raise ValueError('需要一个test_*.c主机行为测试入口；模型应编写覆盖需求与失败边界的实际断言')
    workspace=root/'runtime/draft-checks'/str(uuid4());workspace.mkdir(parents=True)
    production={n:b for n,b in sources.items() if n not in tests}
    arm=ArmccCompiler(os.environ.get('EMBEDDED_AGENT_ARMCC','C:/Keil_v5/ARM/ARMCC/bin/armcc.exe')).compile(production,cpu,workspace/'armcc')
    # Persist object hashes and logs, not a duplicate base64 blob in each prompt.
    arm['objects']={n:{k:v for k,v in info.items() if k!='base64'} for n,info in arm.get('objects',{}).items()}
    host={'status':'unsupported','reason':'本机未配置MSVC x64工具链','hardware':'not_run'}
    vcvars=Path(os.environ.get('EMBEDDED_AGENT_VCVARS','C:/Program Files (x86)/Microsoft Visual Studio/18/BuildTools/VC/Auxiliary/Build/vcvars64.bat'))
    if vcvars.is_absolute() and vcvars.is_file() and not any(c in str(vcvars) for c in ('"','%','!')):
        for name,body in sources.items():(workspace/name).write_text(body,encoding='utf-8')
        command='cl /nologo /W4 /WX /utf-8 /UNDEBUG /TC '+' '.join(sorted(n for n in sources if n.endswith('.c'))) +' /Fe:draft_tests.exe'
        script='@echo off\ncall "'+str(vcvars)+'" >nul\nif errorlevel 1 exit /b 1\n'+command+'\nif errorlevel 1 exit /b 1\ndraft_tests.exe\n'
        (workspace/'run.cmd').write_text(script,encoding='utf-8')
        try:
            run=run_local(['cmd','/c','run.cmd'],cwd=workspace,capture_output=True,timeout=40)
            log=(run.stdout+run.stderr).decode('mbcs' if os.name=='nt' else 'utf-8',errors='replace')[-24000:]
            host={'status':'passed' if run.returncode==0 and (workspace/'draft_tests.exe').exists() else 'failed',
                  'returncode':run.returncode,'log':log,'command':command,'tests':tests,'hardware':'not_run',
                  'scope':'submitted_host_assertions_with_mock_hal'}
            if host['status']=='failed':
                from .assertion_diagnostics import instrument,values
                probe=instrument(sources,log)
                if probe:
                    diagnostic=workspace/'diagnostic';diagnostic.mkdir()
                    from .repair_coach import trace_source,parse_trace,parse_branches,trace_assertions,assertion_progress
                    for name,body in sources.items():
                        replay_body=probe['instrumented_source'] if name==probe['file'] else body
                        if name==probe['file']:
                            replay_body=trace_assertions(replay_body,name)
                        if name.endswith('.c') and not name.startswith('test_'):
                            replay_body=trace_source(replay_body,name)
                        (diagnostic/name).write_text(replay_body,encoding='utf-8')
                    (diagnostic/'run.cmd').write_text(script,encoding='utf-8')
                    try:
                        replay=run_local(['cmd','/c','run.cmd'],cwd=diagnostic,capture_output=True,timeout=40)
                        replay_log=(replay.stdout+replay.stderr).decode('mbcs' if os.name=='nt' else 'utf-8',errors='replace')[-12000:]
                        host['assertion_progress_available']=bool(values(replay_log)) and probe['expression'] in replay_log
                        host['passed_assertions']=assertion_progress((replay.stdout+replay.stderr).decode('mbcs' if os.name=='nt' else 'utf-8',errors='replace'))
                        host['assertion_diagnostic']={k:v for k,v in probe.items() if k!='instrumented_source'}
                        host['assertion_diagnostic'].update(actual_values=values(replay_log),replay_returncode=replay.returncode,
                            log=replay_log,call_trace=parse_trace(replay_log),branch_trace=parse_branches(replay_log),scope='separate_instrumented_host_replay',
                            note='原测试、原结果与源码哈希不变。这里只补充失败时的标量读数；不据重放结果宣称通过。')
                    except (subprocess.TimeoutExpired,OSError) as exc:
                        partial=getattr(exc,'output',b'') or b''
                        if isinstance(partial,bytes):partial=partial.decode('mbcs' if os.name=='nt' else 'utf-8',errors='replace')
                        host['assertion_diagnostic']={'status':'unavailable','reason':type(exc).__name__,'partial_log':partial[-4000:],'note':'诊断重放失败，原测试失败结果保持不变'}
        except subprocess.TimeoutExpired:host={'status':'failed','reason':'主机编译或测试超过40秒，未自动重试','hardware':'not_run'}
        except OSError:host={'status':'unsupported','reason':'本地主机工具访问失败','hardware':'not_run'}
    status='passed' if arm['status']==host['status']=='passed' else 'failed' if 'failed' in (arm['status'],host['status']) else 'unsupported'
    report={'status':status,'source_sha256':source_hash(files),'mcu_compile':arm,'host_tests':host,
            'firmware_link':'not_run','hardware':'not_run','electrical_review':'not_run',
            'scope':'object_compile_and_submitted_host_tests_only','workspace':str(workspace)}
    (workspace/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report
