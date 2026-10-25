"""Pinned-vendor Keil build demonstration followed by model-authored board port."""
import hashlib
import json
from pathlib import Path
import sys
import shutil
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tools')]
from embedded_agent import keil
from embedded_agent.local_model import LocalSettings
from run_expanded_tests import Metered
from port_host_checks import run as host_checks

PORT = ROOT / 'runtime/keil/stm32l031-port'


def project():
    # Demonstration: configure the build tool, not the Agent's application logic.
    previous = json.loads((ROOT / 'runtime/keil-verification-import.json').read_text(encoding='utf-8'))
    tree = ET.parse(ROOT / previous['workspace'] / previous['project_file'])
    target = tree.find('./Targets/Target')
    def setv(path, text):
        node = target.find(path)
        if node is None: raise ValueError(path)
        node.text = text
    setv('TargetName', 'STM32L031K6-Port')
    common = 'TargetOption/TargetCommonOption/'
    for key, value in {'Device':'STM32L031K6','PackID':'','PackURL':'','Cpu':'IRAM(0x20000000,0x2000) IROM(0x08000000,0x8000) CPUTYPE("Cortex-M0+") CLOCK(2097152) ELITTLE',
                       'FlashDriverDll':'','RegisterFile':'','SFDFile':'','OutputDirectory':'.\\Objects\\','OutputName':'RobotL031','ListingPath':'.\\Listings\\'}.items():setv(common+key,value)
    setv('TargetOption/TargetArmAds/ArmAdsMisc/AdsCpuType','"Cortex-M0+"')
    for key, size in [('IRAM','0x2000'),('OCR_RVCT9','0x2000'),('IROM','0x8000'),('OCR_RVCT4','0x8000')]:
        setv('TargetOption/TargetArmAds/ArmAdsMisc/OnChipMemories/'+key+'/Size',size)
    controls='TargetOption/TargetArmAds/Cads/VariousControls/'
    setv(controls+'Define','STM32L031xx')
    setv(controls+'IncludePath','.\\app;.\\vendor\\device;.\\vendor\\cmsis')
    setv(controls+'MiscControls','--c99 --no-multibyte-chars')
    target.remove(target.find('Groups'))
    groups=ET.SubElement(target,'Groups');group=ET.SubElement(groups,'Group');ET.SubElement(group,'GroupName').text='Robot and pinned CMSIS'
    files=ET.SubElement(group,'Files')
    names=['vendor/device/startup_stm32l031xx.s','vendor/device/system_stm32l0xx.c']
    names += ['app/'+n for n in ('robot_app.c','voice_uart.c','board.c','main.c')]
    for name in names:
        file=ET.SubElement(files,'File')
        ET.SubElement(file,'FileName').text=Path(name).name
        ET.SubElement(file,'FileType').text='2' if name.endswith('.s') else '1'
        ET.SubElement(file,'FilePath').text='.\\'+name.replace('/','\\')
    tree.write(PORT/'RobotL031.uvprojx',encoding='utf-8',xml_declaration=True)


def build():
    info=keil.inspect_project(PORT/'RobotL031.uvprojx')
    info.update(workspace=str(PORT.relative_to(ROOT)),project_file='RobotL031.uvprojx',editable={
        str(p.relative_to(PORT)).replace('\\','/'):keil.sha(p) for p in (PORT/'app').glob('*') if p.suffix in ('.c','.h')})
    return keil.build(ROOT,info)


def main():
    if not PORT.exists():
        shutil.copytree(ROOT/'runtime/stm32l031-port',PORT)
    project()
    # Fixed fail-closed build configuration; no invented rail GPIO, voice protocol or calibration.
    (PORT/'app/board_config.h').write_text('''#ifndef BOARD_CONFIG_H
#define BOARD_CONFIG_H
#define BOARD_ARMED 0
#define BOARD_VOICE_BAUD 0u
#define BOARD_PWM_HZ 50u /* design assumption, not measured */
#endif
''',encoding='utf-8')
    app={p.name:p.read_text(encoding='utf-8') for p in (PORT/'app').glob('*') if p.suffix in ('.c','.h')}
    original={n:hashlib.sha256(app[n].encode()).hexdigest() for n in ('robot_app.c','robot_app.h','voice_uart.c','voice_uart.h','board_config.h')}
    resume='--resume' in sys.argv
    if not resume:
        # A small tool demonstration is compiled before asking the Agent to implement the real adapter.
        (PORT/'app/board.c').write_text('/* Toolchain demonstration only; replaced by Agent adapter. */\n',encoding='utf-8')
        (PORT/'app/main.c').write_text('#include "stm32l0xx.h"\nint main(void){SystemCoreClockUpdate();for(;;){__WFI();}}\n',encoding='utf-8')
    demo=build();(PORT/('resume-build.json' if resume else 'demonstration-build.json')).write_text(json.dumps(demo,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Demonstration build:',demo['status'],demo.get('log','')[-1200:],flush=True)
    if demo['status']!='passed':raise SystemExit('Toolchain demonstration failed; model not called')
    model=Metered(LocalSettings(ROOT).model())
    previous=json.loads((PORT/'port-report.json').read_text(encoding='utf-8')) if resume else {}
    history=previous.get('history',[])
    if resume:
        history.append({'status':'failed','log':'Additional frozen register-mock tests and warnings must be fixed.','files':{n:(PORT/'app'/n).read_text(encoding='utf-8') for n in ('board.c','board.h','main.c')},'host_tests':host_checks(PORT)})
    instruction='''编写STM32L031K6 Cortex-M0+板级适配C99，只返回files(board.h,board.c,main.c)与rationale。禁止改动应用、配置、官方源码和工程。
board.h定义void board_init(void), const robot_hal_t *board_hal(void), int board_uart_read(uint8_t *out)。
SysTick_Handler累计volatile uint32_t毫秒，board_init调用SystemCoreClockUpdate和SysTick_Config(SystemCoreClock/1000)，失败不可继续运行。使用复位MSI约2097152Hz，不虚构外部晶振。默认BOARD_ARMED=0：只初始化SysTick，禁止配置GPIO复用、启用TIM2/UART或发PWM；servo_rail_enable必须默认无操作，不能猜测负载开关引脚/极性。
保留可编译的候选TIM2板级实现：PA5 AF5 CH1、PA2 AF2 CH3、PA3 AF2 CH4，轴yaw/pitch/wave按此顺序只是候选布线假设；50Hz是设计假设。仅BOARD_ARMED且时钟整除1000000且PSC可用才允许初始化PWM，否则禁用，因MSI不是整MHz默认不可使能。TIM2 CCR初始0，脉宽1000..2000范围之外拒绝，采用预装载，映射正确禁止通道2。输出关闭时CCR与CCER关闭。由于电源控制未定，无论ARMED都不允许真正接通舵机电源。
UART PA9 AF4 USART2_TX、PA10 AF4 USART2_RX，只有BOARD_ARMED && BOARD_VOICE_BAUD>0且BRR合法才初始化，否则board_uart_read返回0；串口错误丢弃并清标志，不把错误数据传入应用。不使用中断收UART，轮询即可。禁止默认命令字和标定值。
main调用board_init、robot_init、voice_proto_init，保留默认configured=0且不设置calibrated；循环board_uart_read -> voice_feed_byte -> 合法命令调用robot_handle_cmd，并始终robot_tick；不能声称SU-21T实际协议已完成。禁止动态分配、semihosting、stdio或无界硬件等待。
演示仅示范工程配置，不是待复制的适配。你需自行写完整适配；若编译失败按实际日志修复。
验收要求无编译警告，不得靠关闭警告掩盖；未启用分支的helper需合理条件编译。servo_rail_enable(0)在已初始化PWM的情况下必须清CCR1/3/4并关闭CCER通道，enable(1)仍不得猜测实际电源GPIO；board_init重复调用必须先关闭此前已初始化的PWM输出和UART，再清ready flags，防止失效时钟/新初始化失败后旧硬件输出仍在继续。关闭操作只在此前ready或已启用的外设时钟可证明寄存器可访问时执行，默认ARMED0仍禁止碰外设。UART错误必须读RDR丢掉错误数据并清错误标志。冻结主机寄存器替身测试也必须通过（替身不模拟读写副作用）。'''
    header=(PORT/'vendor/device/stm32l031xx.h').read_text(encoding='utf-8')
    # Vendor register structures and exact macro names only; avoid resending the entire device header.
    import re
    structs='\n'.join(re.findall(r'typedef struct\s*\{.*?\}\s*(?:GPIO|RCC|TIM|USART)_TypeDef;',header,re.S))
    macros='\n'.join(line for line in header.splitlines() if line.startswith('#define ') and any(x in line.split()[1] for x in ('RCC_IOPENR','RCC_APB1ENR','USART_ISR_','USART_ICR_','USART_CR1_','TIM_CR1_','TIM_CCMR','TIM_CCER','TIM_EGR')))
    for turn in range(3):
        answer=model.generate(role='stm32_port_writer',instruction=instruction,context={'application':{n:app[n] for n in original},'register_structures':structs[-18000:],'register_macros':macros,'previous_attempt':history[-1] if history else None})
        index=len(list(PORT.glob('agent-attempt-*.json')))+1
        (PORT/f'agent-attempt-{index}.json').write_text(json.dumps(answer,ensure_ascii=False,indent=2),encoding='utf-8')
        files=answer.get('files',{})
        if set(files)!= {'board.h','board.c','main.c'} or any(not isinstance(s,str) or not s.strip() for s in files.values()):
            history.append({'status':'failed','log':'files must contain exactly board.h, board.c and main.c'});continue
        for name,body in files.items():(PORT/'app'/name).write_text(body,encoding='utf-8')
        result=build();host=host_checks(PORT)
        passed=result['status']=='passed' and not any(d['severity']=='warning' for d in result.get('diagnostics',[])) and all(r['status']=='passed' for r in host)
        history.append({'status':'passed' if passed else 'failed','log':result.get('log',result.get('reason','')),'files':files,'host_tests':host})
        (PORT/f'build-{index}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print('Agent build',turn+1,result['status'],result.get('log','')[-1500:],flush=True)
        if passed:break
    unchanged=all(hashlib.sha256((PORT/'app'/n).read_text(encoding='utf-8').encode()).hexdigest()==h for n,h in original.items())
    calls=previous.get('calls',[])+model.calls
    report={'status':history[-1]['status'],'demonstration':'Codex toolchain setup','adapter_author':'configured DeepSeek Agent','calls':calls,'cost_cny':sum(c['accounted_cny'] for c in calls),'immutable_sources_unchanged':unchanged,'hardware':'not_run','outputs_armed':False,'history':history}
    (PORT/'port-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('calls','history')},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
