"""Agent-authored F103 candidate board port, actual uVision link, no flashing."""

import os
# Public helper: configure EMBEDDED_PROJECT_ID_1 before use.
from pathlib import Path
import json,sys,shutil,xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tools')]
from embedded_agent.service import EngineeringService
from embedded_agent.local_model import LocalSettings
from embedded_agent import keil
from run_expanded_tests import Metered

def main():
 s=EngineeringService(ROOT);pid=os.environ['EMBEDDED_PROJECT_ID_1'];p=s.get(pid)
 folder=ROOT/'runtime/keil/dog-firmware';folder.mkdir(parents=True,exist_ok=True)
 old=json.loads((ROOT/'runtime/keil-verification-import.json').read_text(encoding='utf-8'));template=ROOT/old['workspace']
 shutil.copytree(template/'Start',folder/'Start',dirs_exist_ok=True)
 app=folder/'app';app.mkdir(exist_ok=True)
 files=p['artifacts']['mcu_implementation']['files']
 for n,b in files.items():(app/n).write_text(b,encoding='utf-8')
 (app/'board_config.h').write_text('#define ROBOT_OUTPUTS_ARMED 0\n#define ROBOT_UART_BAUD 0u\n/* Pins and baud are candidate assumptions; enable only after review. */\n')
 tree=ET.parse(template/'Project.uvprojx');target=tree.find('./Targets/Target');target.find('TargetName').text='Dog-F103-Candidate'
 target.find('.//Cads/VariousControls/Define').text='STM32F10X_MD'
 target.find('.//Cads/VariousControls/IncludePath').text='.\\Start;.\\app'
 target.find('.//Cads/VariousControls/MiscControls').text='--c99 --no-multibyte-chars'
 target.remove(target.find('Groups'));g=ET.SubElement(ET.SubElement(target,'Groups'),'Group');ET.SubElement(g,'GroupName').text='Dog firmware';fs=ET.SubElement(g,'Files')
 names=['Start/startup_stm32f10x_md.s']+['app/'+n for n in files if n.endswith('.c') and not n.startswith('test_')]+['app/system_port.c']
 for n in names:
  f=ET.SubElement(fs,'File');ET.SubElement(f,'FileName').text=Path(n).name;ET.SubElement(f,'FileType').text='2' if n.endswith('.s') else '1';ET.SubElement(f,'FilePath').text=n.replace('/','\\')
 tree.write(folder/'Dog.uvprojx',encoding='utf-8',xml_declaration=True)
 model=Metered(LocalSettings(ROOT).model());history=[]
 for turn in range(3):
  answer=model.generate(role='firmware_port_writer',instruction='编写候选STM32F103C8T6板级适配，仅返回board_hal.c、servo_pwm.c、system_port.c。现有应用和头文件不修改。使用stm32f10x.h CMSIS寄存器，不依赖标准外设库。SystemInit显式使用内部HSI 8MHz（不可假设板载晶振），有界等待HSI准备，清总线分频，切HSI；定义SystemCoreClock=8000000及SystemCoreClockUpdate从固定HSI方案更新。SysTick_Config 1ms，SysTick_Handler递增毫秒，Board_GetTickMs返回，Board_SleepIdle使用__WFI。USART1 PA9/PA10候选，轮询接收，出错丢字节；波特率ROBOT_UART_BAUD=0代表未知必须禁用。TIM2 PA0..3 CH1..4候选，50Hz，PSC基于8MHz得到1MHz计数，CCR初始0；脉宽限界使用现有servo/app_config常量；通道范围与脉宽钳位；初始化先保持输出禁用。ROBOT_OUTPUTS_ARMED=0默认：禁止外设GPIO复用配置、禁止舵机PWM和USART使能，不虚构电源开关；毫秒中断和主循环仍真实接通。只在明确ARMED且参数合法时允许候选GPIO/PWM/UART；未知实际板卡、标定和蓝牙模块协议不能声称已验证。所有启用分支都必须能被真实头文件编译检查；不要用#if隐藏其语法错误，使用运行期常量条件也可。无需main，因为已有main.c。不得动态内存或semihosting。编译失败按真实日志最小修复。',context={'current_sources':files,'board_config':(app/'board_config.h').read_text(),'previous':history[-1] if history else None})
  (folder/f'agent-{turn+1}.json').write_text(json.dumps(answer,ensure_ascii=False,indent=2),encoding='utf-8')
  generated=answer.get('files',{})
  if set(generated)!={'board_hal.c','servo_pwm.c','system_port.c'}:raise ValueError('Unexpected port files')
  for n,b in generated.items():(app/n).write_text(b,encoding='utf-8')
  info=keil.inspect_project(folder/'Dog.uvprojx');info.update(workspace=str(folder.relative_to(ROOT)),project_file='Dog.uvprojx',editable={str(x.relative_to(folder)).replace('\\','/'):keil.sha(x) for x in app.glob('*') if x.suffix in ('.c','.h')})
  result=keil.build(ROOT,info);history.append({'status':result['status'],'log':result.get('log'), 'files':generated})
  (folder/f'build-{turn+1}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print('build',turn+1,result['status'],result.get('log','')[-1500:],flush=True)
  if result['status']=='passed' and not any(d['severity']=='warning' for d in result.get('diagnostics',[])):break
 report={'status':history[-1]['status'],'calls':model.calls,'cost_cny':sum(c['accounted_cny'] for c in model.calls),'history':history,'hardware':'not_run','board_configuration':'candidate_only_outputs_disabled'}
 if report['status']=='passed':
  p=s.get(pid);p=s.update(pid,p['revision'],'keil_import',{'confirmed':True,'file':str(folder/'Dog.uvprojx')});p=s.update(pid,p['revision'],'keil_build',{})
  if p['artifacts']['keil_build']['status']!='passed':raise ValueError('Imported project rebuild failed')
  p=s.update(pid,p['revision'],'execute',{});(folder/'小狗候选固件验证包.zip').write_bytes(s.download(pid));report['project_revision']=p['revision']
 (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({k:v for k,v in report.items() if k not in ('calls','history')},ensure_ascii=False))

if __name__=='__main__':main()
