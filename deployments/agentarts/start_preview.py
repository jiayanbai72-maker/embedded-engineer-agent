"""Start an isolated preview on 8786; never restarts or rewrites the 8765 app."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import urlopen
import webbrowser


def main(open_browser=True):
    root = Path(__file__).resolve().parents[2]
    runtime = root / 'runtime/agentarts-preview'; runtime.mkdir(parents=True, exist_ok=True)
    url = 'http://127.0.0.1:8786'
    def healthy():
        try:
            with urlopen(url + '/health', timeout=1) as response:
                return json.load(response).get('scope') == 'agentarts_document_engineering'
        except (OSError, ValueError): return False
    if not healthy():
        with socket.socket() as probe:
            try: probe.bind(('127.0.0.1', 8786))
            except OSError: raise ValueError('8786已被其他进程占用，未停止任何服务') from None
        args = [sys.executable, '-X', 'utf8', '-m', 'deployments.agentarts.app', '--preview']
        config = root / 'runtime/agentarts-local-config.json'
        if config.is_file(): args += ['--config', str(config)]
        env = os.environ.copy(); env['PYTHONPATH'] = str(root / 'src'); env['CLOUD_PORT'] = '8786'; env.pop('CLOUD_STATE_DIR', None)
        flags = getattr(subprocess, 'DETACHED_PROCESS', 0) | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
        with (runtime / 'stdout.log').open('ab') as out, (runtime / 'stderr.log').open('ab') as err:
            process = subprocess.Popen(args, cwd=root, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                       creationflags=flags, close_fds=True, start_new_session=os.name != 'nt')
        (runtime / 'preview.pid').write_text(str(process.pid), encoding='utf-8')
        for _ in range(30):
            if healthy(): break
            if process.poll() is not None: raise ValueError('预览启动失败，请查看runtime/agentarts-preview/stderr.log')
            time.sleep(0.2)
        else: raise ValueError('预览尚未就绪，请查看独立预览日志')
    print('AgentArts本地适配预览：' + url + '；原工作台仍为 http://127.0.0.1:8765/')
    if open_browser: webbrowser.open(url)


if __name__ == '__main__': main('--no-open' not in sys.argv)
