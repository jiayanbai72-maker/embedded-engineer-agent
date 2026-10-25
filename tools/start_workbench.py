"""Launch the local workbench without requiring PowerShell script execution."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser


def healthy(url):
    try:
        with urllib.request.urlopen(url + '/health', timeout=1) as response:
            data = json.load(response)
        return data.get('status') == 'ok' and data.get('mode') == 'analyst_assisted'
    except (OSError, ValueError):
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--no-open', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('端口范围不正确')
    root = Path(__file__).absolute().parents[1]
    url = f'http://127.0.0.1:{args.port}'
    if not healthy(url):
        with socket.socket() as probe:
            try:
                probe.bind(('127.0.0.1', args.port))
            except OSError:
                raise RuntimeError('端口不可用，请检查是否有其他服务占用。') from None
        environment = dict(os.environ, PYTHONPATH=str(root / 'src'))
        compiler = Path(r'C:\Keil_v5\ARM\ARMCC\bin\armcc.exe')
        if compiler.is_file() and not environment.get('EMBEDDED_AGENT_ARMCC'):
            environment['EMBEDDED_AGENT_ARMCC'] = str(compiler)
        runtime = root / 'runtime'
        runtime.mkdir(exist_ok=True)
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
        with (runtime / 'server.stdout.log').open('ab') as out, (runtime / 'server.stderr.log').open('ab') as err:
            process = subprocess.Popen([sys.executable, '-X', 'utf8', '-m', 'embedded_agent.server', '--port', str(args.port)],
                                       cwd=root, env=environment, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                       creationflags=flags, start_new_session=os.name != 'nt')
        deadline = time.monotonic() + 15
        while not healthy(url):
            if process.poll() is not None or time.monotonic() >= deadline:
                raise RuntimeError('服务启动失败，请查看 runtime/server.stderr.log。')
            time.sleep(0.3)
        (runtime / 'server.pid').write_text(str(process.pid), encoding='ascii')
    print('工作台已就绪：' + url + '/')
    if not args.no_open:
        webbrowser.open(url + '/')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('启动失败：' + str(exc), file=sys.stderr)
        sys.exit(1)
