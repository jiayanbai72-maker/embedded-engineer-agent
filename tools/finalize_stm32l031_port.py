"""Revalidate both build branches, restore safe configuration, and package evidence."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess
from zipfile import ZipFile, ZIP_DEFLATED
from run_stm32l031_port import PORT, build
from port_host_checks import run


def main():
    config=PORT/'app/board_config.h';original=config.read_bytes()
    try:
        config.write_text('#define BOARD_ARMED 1\n#define BOARD_VOICE_BAUD 1000000u\n#define BOARD_PWM_HZ 50u\n')
        enabled=build()
        (PORT/'enabled-branch-build.json').write_text(json.dumps(enabled,ensure_ascii=False,indent=2),encoding='utf-8')
    finally:config.write_bytes(original)
    safe=build()
    (PORT/'safe-final-build.json').write_text(json.dumps(safe,ensure_ascii=False,indent=2),encoding='utf-8')
    (PORT/'safe-final-build.log').write_text(safe.get('log',''),encoding='utf-8')
    host=run(PORT)
    fromelf=Path('C:/Keil_v5/ARM/ARMCC/bin/fromelf.exe')
    subprocess.run([str(fromelf),'--bin','--output=Objects/RobotL031.bin','Objects/RobotL031.axf'],cwd=PORT,check=True,capture_output=True,timeout=20)
    binary=(PORT/'Objects/RobotL031.bin').read_bytes();sp,reset=struct.unpack_from('<II',binary)
    image_ok=0<len(binary)<=32768 and 0x20000000<sp<=0x20002000 and sp%8==0 and reset&1 and 0x08000000<=(reset&~1)<0x08000000+len(binary)
    report=json.loads((PORT/'port-report.json').read_text(encoding='utf-8'))
    report['final_validation']={'enabled_branch_compile':enabled['status'],'safe_build':safe['status'],'host_register_tests':host,
        'image_checks':{'passed':bool(image_ok),'bin_bytes':len(binary),'stack_pointer':hex(sp),'reset_vector':hex(reset)},
        'regression':'225 tests, OK, skipped=2',
        'fixture_correction':'Excluded real peripheral pointer aliases from mock header. Earlier failing host results due to fixture are preserved in history.',
        'scope':'compile_link_and_mock_register_assertions_not_device_execution'}
    report['status']='passed' if image_ok and enabled['status']==safe['status']=='passed' and not any(d['severity']=='warning' for r in (enabled,safe) for d in r.get('diagnostics',[])) and all(r['status']=='passed' for r in host) else 'failed'
    hits=sum(c.get('cache_hit_tokens') or 0 for c in report['calls']);miss=sum(c.get('cache_miss_tokens') or 0 for c in report['calls'])
    report['cache_hit_ratio']=hits/(hits+miss) if hits+miss else None
    report['output_hashes']={str(p.relative_to(PORT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (PORT/'Objects').glob('RobotL031.*') if p.suffix in ('.axf','.bin','.hex')}
    (PORT/'port-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    readme=f'''# STM32L031K6 固件适配与编译验证

状态：{report['status']}；未连接硬件、未烧录。此包不是已验收的整机固件。

打开 RobotL031.uvprojx，选择 STM32L031K6-Port，使用本机 ARMCC 5.06 编译。
目标 Cortex-M0+，Flash 32KiB、RAM 8KiB。ST 官方启动文件和系统文件的固定提交、下载来源及哈希见 vendor-manifest.json；CMSIS 来自本机包，许可文件随附。

## 谁完成了什么

Codex：工程配置示范、工具编排、冻结测试与结果检查；修正测试替身地址宏覆盖问题。
已配置 DeepSeek Agent：board.c、board.h、main.c；根据实际警告和测试反馈修复。未修改原应用四个文件、官方源码和冻结配置。此处是有限次数的编译修复演练，不代表所有报错都能自动解决。

## 本次通过的检查

- Keil 默认禁用配置：编译、链接、导出 HEX，0 错误、0 警告。
- 用真实芯片头文件编译候选启用分支：0 错误、0 警告；只编译，不执行。
- 固定主机寄存器替身测试：默认输出禁用、SysTick计数、三路PWM映射、范围检查、关断清输出、串口错误拒收、重复初始化的旧输出清理。
- BIN大小、初始栈和Thumb复位入口范围检查；项目离线回归225项（2项跳过）。

## 默认配置与尚未完成的部分

BOARD_ARMED=0，BOARD_VOICE_BAUD=0。默认固件只有时基和应用主循环；不会配置PWM/UART引脚或驱动舵机。
复位MSI约2.097152MHz，不是整MHz；当前候选1MHz PWM实现对此拒绝使能。下一步需选择并验证合适时钟方案，而非将BOARD_ARMED改为1就能工作。
PA5/PA2/PA3对应TIM2_CH1/CH3/CH4，PA9/PA10对应USART2。轴与候选引脚关系是布线假设，不是实物确认。
舵机供电开关引脚与极性未确定，电源回调从不接通电源；关断请求会清理已初始化PWM。
语音模块真实协议、波特率、舵机标定、实际供电、电气和时序、功耗及续航尚未验证。main保持语音configured=0且不写入伪造标定。
模拟启用测试采用16MHz和1Mbaud只为覆盖代码分支，不能当作语音模块真实配置。寄存器替身不模拟真实硬件副作用。

## 记录

port-report.json保存作者、调用回执、实际失败和修复历史及最终验证。
本次模型调用{len(report['calls'])}次，保守结算约¥{report['cost_cny']:.4f}；缓存命中率{report['cache_hit_ratio']:.1%}。
safe-final-build.log为最终禁用配置的实际编译日志。
'''
    (PORT/'README.md').write_text(readme,encoding='utf-8')
    archive=PORT.parent/'STM32L031固件适配验证包.zip'
    with ZipFile(archive,'w',ZIP_DEFLATED) as z:
        for path in PORT.rglob('*'):
            if not path.is_file():continue
            rel=path.relative_to(PORT)
            if rel.parts[0] in ('vendor','app') or path.suffix in ('.uvprojx','.json','.md') or rel.as_posix()=='safe-final-build.log' or str(rel) in report['output_hashes']:
                z.write(path,rel)
        z.write(PORT/'Listings/RobotL031.map','Listings/RobotL031.map')
    print(json.dumps({'status':report['status'],'cost_cny':report['cost_cny'],'calls':len(report['calls']),'cache_hit_ratio':report['cache_hit_ratio'],'image_checks':report['final_validation']['image_checks'],'archive':str(archive)},ensure_ascii=False))
    if report['status']!='passed':raise SystemExit(1)


if __name__=='__main__':main()
