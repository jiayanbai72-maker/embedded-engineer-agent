"""Device discovery and explicitly bound receive-only serial capture; no flash/write."""
import base64
from datetime import datetime, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4


def serial_modules(root):
    dependency = Path(root) / 'runtime' / 'dependencies'
    if dependency.is_dir() and str(dependency) not in sys.path: sys.path.insert(0, str(dependency))
    try: return importlib.import_module('serial'), importlib.import_module('serial.tools.list_ports')
    except ImportError: return None, None


def identity(port):
    fields = {key: getattr(port, key, None) for key in ('device', 'description', 'hwid', 'vid', 'pid', 'serial_number', 'manufacturer', 'product', 'location')}
    fields['fingerprint'] = hashlib.sha256(json.dumps(fields, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    fields.update(board_model=None, mcu=None, confidence='transport_only',
                  explanation='串口描述来自操作系统；USB转串口芯片与端口号不能证明主控或板卡型号')
    return fields


def discover(root):
    serial, ports = serial_modules(root)
    if serial is None:
        return {'status': 'unsupported', 'ports': [], 'reason': '缺少可选依赖 pyserial；未检测设备', 'opened_device': False}
    try: found = [identity(p) for p in ports.comports()]
    except OSError: return {'status': 'failed', 'ports': [], 'reason': '操作系统端口枚举失败', 'opened_device': False}
    return {'status': 'passed', 'ports': found, 'opened_device': False,
            'reason': '发现串口；板卡型号仍需结合其他证据' if found else '未发现串口；设备可能未连接、未安装驱动或没有串口接口',
            'board_catalog': {'complete': False, 'identification': '操作系统描述与USB元数据；没有完整开发板型号库'}}


def usb_inventory():
    if os.name != 'nt': return {'status': 'unsupported', 'devices': [], 'reason': '当前仅实现Windows USB元数据枚举'}
    command = "$ErrorActionPreference='Stop'; @(Get-CimInstance Win32_PnPEntity | Where-Object { $_.PNPDeviceID -like 'USB\\*' -and $_.Present } | Select-Object Name,PNPClass,PNPDeviceID,Status) | ConvertTo-Json -Compress"
    try:
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command], capture_output=True,
                                timeout=12, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode: raise ValueError('枚举未成功')
        raw = result.stdout.decode('utf-8-sig', errors='replace')
        if '\ufffd' in raw: raw = result.stdout.decode('gb18030', errors='replace')
        data = json.loads(raw) if raw.strip() else []
        return {'status': 'passed', 'devices': data if isinstance(data, list) else [data],
                'opened_device': False, 'interpretation': '仅USB设备清单；摄像头、蓝牙及集线器不自动视为开发板'}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {'status': 'failed', 'devices': [], 'reason': 'USB清单读取失败或权限不足；不等于没有USB设备'}


def bind(root, payload):
    if payload.get('confirmed') is not True: raise ValueError('需要用户确认选定端口及只接收日志权限')
    baud = payload.get('baudrate')
    if type(baud) is not int or not 300 <= baud <= 3_000_000: raise ValueError('波特率必须在300至3000000之间')
    current = discover(root)
    if current['status'] != 'passed': raise ValueError(current.get('reason', '端口枚举失败'))
    selected = next((p for p in current['ports'] if p['device'] == payload.get('port') and p['fingerprint'] == payload.get('fingerprint')), None)
    if selected is None: raise ValueError('设备已变化或端口未发现，请刷新设备列表后选择')
    return {'id': str(uuid4()), 'port': selected, 'baudrate': baud, 'bytesize': 8, 'parity': 'N', 'stopbits': 1,
            'scope': 'serial_receive_only', 'permission': 'user_confirmed', 'board_label': payload.get('board_label', ''),
            'board_identity_verified': False, 'hardware_test': 'not_run'}


def capture(root, binding, seconds=3):
    if type(seconds) is not int or not 1 <= seconds <= 10: raise ValueError('采集时长必须为1至10秒')
    if binding.get('permission') != 'user_confirmed' or binding.get('scope') != 'serial_receive_only': raise ValueError('缺少串口采集授权')
    current = discover(root)
    selected = next((p for p in current['ports'] if p['fingerprint'] == binding['port']['fingerprint']), None)
    if current['status'] != 'passed' or selected is None: raise ValueError('设备断开或身份信息已变化，需重新选择并授权')
    serial, _ = serial_modules(root)
    started = datetime.now(timezone.utc).isoformat()
    connection = serial.Serial(port=None, baudrate=binding['baudrate'], bytesize=8, parity='N', stopbits=1, timeout=0.2,
                               write_timeout=0.2, rtscts=False, dsrdtr=False, xonxoff=False)
    connection.port = selected['device']; connection.dtr = False; connection.rts = False
    data = bytearray(); error = None
    try:
        connection.open()
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline and len(data) < 65536:
            data.extend(connection.read(min(4096, 65536 - len(data))))
    except (OSError, serial.SerialException): error = '端口打开或读取失败，可能被占用、断开或权限不足'
    finally:
        if connection.is_open: connection.close()
    raw = bytes(data)
    return {'id': str(uuid4()), 'status': 'failed' if error else 'captured' if raw else 'no_data',
            'binding_id': binding['id'], 'port': selected, 'baudrate': binding['baudrate'], 'started_utc': started,
            'ended_utc': datetime.now(timezone.utc).isoformat(), 'seconds': seconds, 'bytes': len(raw),
            'raw_base64': base64.b64encode(raw).decode(), 'sha256': hashlib.sha256(raw).hexdigest(),
            'text': raw.decode('utf-8', errors='replace'), 'decoding': 'UTF-8预览，原始字节保留', 'error': error,
            'truncated': len(raw) >= 65536, 'commands_sent': False, 'hardware_test': 'not_run'}
