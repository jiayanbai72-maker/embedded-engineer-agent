"""ARMCC image builder with explicit demonstration-board profile and image checks."""
import base64
import hashlib
import os
from pathlib import Path
import struct
import subprocess
from uuid import uuid4
from .mcu import ArmccCompiler, validate_sources


def validate_profile(profile):
    if not isinstance(profile, dict) or profile.get('cpu') != 'Cortex-M3' or profile.get('mode') != 'demonstration_only':
        raise ValueError('当前完整链接仅支持明确标记的Cortex-M3演练配置')
    for key in ('flash_base', 'flash_size', 'ram_base', 'ram_size', 'stack_size'):
        value = profile.get(key)
        if type(value) is not int or value < 0 or value % 8 or value > 0xffffffff:
            raise ValueError('内存参数必须为8字节对齐的32位非负整数')
    if not 64 <= profile['flash_size'] <= 1024 * 1024 or not 1024 <= profile['ram_size'] <= 1024 * 1024:
        raise ValueError('内存容量超出当前演练范围')
    if not 256 <= profile['stack_size'] <= profile['ram_size'] // 2:
        raise ValueError('栈容量不正确')
    fb, fe = profile['flash_base'], profile['flash_base'] + profile['flash_size']
    rb, re = profile['ram_base'], profile['ram_base'] + profile['ram_size']
    if fe > 2**32 or re > 2**32 or max(fb, rb) < min(fe, re):
        raise ValueError('内存溢出或FLASH/RAM重叠')
    if fb % 128:
        raise ValueError('向量表基址必须至少128字节对齐')


def layout(profile):
    validate_profile(profile)
    return f'''LR_FLASH 0x{profile['flash_base']:08X} 0x{profile['flash_size']:X} {{
  ER_FLASH 0x{profile['flash_base']:08X} 0x{profile['flash_size']:X} {{
    startup.o (RESET, +First)
    *(InRoot$$Sections)
    .ANY (+RO)
  }}
  RW_RAM 0x{profile['ram_base']:08X} 0x{profile['ram_size']:X} {{
    .ANY (+RW +ZI)
  }}
}}
'''


def startup(profile):
    validate_profile(profile)
    return f'''        PRESERVE8
        THUMB
        AREA STACK, NOINIT, READWRITE, ALIGN=3
Stack_Mem SPACE {profile['stack_size']}
__initial_sp
        AREA RESET, DATA, READONLY
        EXPORT __Vectors
__Vectors
        DCD __initial_sp
        DCD Reset_Handler
        DCD Default_Handler, Default_Handler, Default_Handler, Default_Handler
        DCD Default_Handler, 0, 0, 0, 0, Default_Handler
        DCD Default_Handler, 0, Default_Handler, Default_Handler
        AREA |.text|, CODE, READONLY
Reset_Handler PROC
        EXPORT Reset_Handler
        IMPORT __main
        LDR R0, =__main
        BX R0
        ENDP
Default_Handler PROC
        B .
        ENDP
        END
'''


def check_images(binary, ihex, profile):
    validate_profile(profile)
    if not 64 <= len(binary) <= profile['flash_size']:
        raise ValueError('BIN容量不正确')
    sp, reset = struct.unpack_from('<II', binary)
    if not profile['ram_base'] < sp <= profile['ram_base'] + profile['ram_size'] or sp % 8:
        raise ValueError('初始栈地址越界或未对齐')
    address = reset & ~1
    if not reset & 1 or not profile['flash_base'] <= address < profile['flash_base'] + len(binary):
        raise ValueError('复位向量不是有效Thumb入口')
    high, data, eof = 0, {}, False
    for line in ihex.decode('ascii').splitlines():
        if eof or not line.startswith(':'):
            raise ValueError('HEX记录格式不正确')
        raw = bytes.fromhex(line[1:])
        if len(raw) < 5 or len(raw) != raw[0] + 5 or sum(raw) % 256:
            raise ValueError('HEX校验和或长度错误')
        size, pos, kind = raw[0], int.from_bytes(raw[1:3], 'big'), raw[3]
        payload = raw[4:-1]
        if kind == 0:
            for i, byte in enumerate(payload):
                absolute = high + pos + i
                if absolute in data:
                    raise ValueError('HEX记录重叠')
                data[absolute] = byte
        elif kind == 4 and size == 2:
            high = int.from_bytes(payload, 'big') << 16
        elif kind == 2 and size == 2:
            high = int.from_bytes(payload, 'big') << 4
        elif kind == 1 and size == 0:
            eof = True
        elif kind in (3, 5) and size == 4:
            pass
        else:
            raise ValueError('HEX记录类型不支持')
    if not eof or not data or any(not 0 <= a - profile['flash_base'] < len(binary) or binary[a - profile['flash_base']] != b for a, b in data.items()):
        raise ValueError('HEX与BIN数据不一致')
    if any(data.get(profile['flash_base'] + i) != binary[i] for i in range(64)):
        raise ValueError('HEX缺少完整向量表')
    return {'status': 'passed', 'stack_pointer': sp, 'reset_vector': reset, 'bin_bytes': len(binary),
            'hex_data_bytes': len(data), 'checks': ['vector_range', 'thumb_entry', 'memory_bounds', 'hex_checksum', 'hex_bin_consistency'], 'hardware': 'not_run'}


def build_firmware(root, project):
    impl = project.artifacts['firmware_implementation']
    profile, files = impl['profile'], impl['files']
    validate_profile(profile); validate_sources(files, profile['cpu'])
    directory = root / 'runtime' / 'firmware-runs' / project.id / str(uuid4())
    executable = Path(os.environ.get('EMBEDDED_AGENT_ARMCC', ''))
    result = ArmccCompiler(executable).compile(files, profile['cpu'], directory)
    result.update(scope='mcu_firmware_build', profile=profile, images={}, firmware_link='not_run', image_checks={'status': 'not_run'})
    if result['status'] != 'passed':
        return result
    result['status'] = 'failed'
    generated = {'startup.s': startup(profile), 'layout.sct': layout(profile)}
    result['generated_sources'] = generated
    for name, body in generated.items():
        (directory / name).write_text(body, encoding='utf-8')
    bins = executable.parent
    commands = [
        [str(bins / 'armasm.exe'), '--cpu=Cortex-M3', 'startup.s', '-o', 'startup.o'],
        [str(bins / 'armlink.exe'), '--scatter=layout.sct', '--entry=Reset_Handler', '--map', '--list=firmware.map', '-o', 'firmware.axf', 'startup.o'] + sorted(result['objects']),
        [str(bins / 'fromelf.exe'), '--bin', '--output=firmware.bin', 'firmware.axf'],
        [str(bins / 'fromelf.exe'), '--i32', '--output=firmware.hex', 'firmware.axf'],
    ]
    try:
        for index, command in enumerate(commands):
            run = subprocess.run(command, cwd=directory, capture_output=True, timeout=20)
            result['commands'].append({'argv': command, 'returncode': run.returncode})
            result['log'] += '\n' + (run.stdout + run.stderr).decode('utf-8', errors='replace')
            if run.returncode != 0:
                return dict(result, reason='汇编、链接或导出失败')
            if index == 1:
                result['firmware_link'] = 'passed'
        binary, ihex = (directory / 'firmware.bin').read_bytes(), (directory / 'firmware.hex').read_bytes()
        if not (directory / 'firmware.axf').read_bytes().startswith(b'\x7fELF'):
            raise ValueError('链接输出不是ELF')
        result['image_checks'] = check_images(binary, ihex, profile)
        for name in ('firmware.axf', 'firmware.bin', 'firmware.hex', 'firmware.map'):
            raw = (directory / name).read_bytes()
            if len(raw) > 2_000_000:
                raise ValueError('产物超过限制')
            result['images'][name] = {'sha256': hashlib.sha256(raw).hexdigest(), 'size_bytes': len(raw), 'base64': base64.b64encode(raw).decode('ascii')}
        result['status'] = 'passed'
        return result
    except subprocess.TimeoutExpired:
        return dict(result, reason='构建工具超时')
    except (OSError, ValueError):
        return dict(result, reason='产物读取或校验失败')
