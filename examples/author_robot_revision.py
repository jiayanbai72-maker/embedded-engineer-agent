"""Case submission authored after reading actual round-1 observations, not a provider."""
from copy import deepcopy
import json
from pathlib import Path

root=Path(__file__).resolve().parents[1]
project=json.loads((root/'runtime/projects/f1e32762-d0b1-4dae-a6d5-0ef2db0fa94a.json').read_text(encoding='utf-8'))
previous=project['artifacts']['design_loop']['rounds'][-1]
if previous['number']!=1: raise ValueError('此示例只用于已观察的第一轮之后，不能盲目重放')
failed=next(e for e in previous['evaluations'] if e['candidate_id']=='DEV_BOARD')['report']['checks'][1]
if failed['calculation_status']!='failed' or failed['status']!='needs_evidence': raise ValueError('实际观察与本次分析前提不同，请重新判断')
plan=deepcopy(previous['plan']); candidate=plan['candidates'][1]
candidate['name']='集成语音主控的精简备选（开发与三路PWM待验证）'
candidate['architecture']='探索由SU21T内部主控完成离线识别和动作控制，外接3路舵机及断电开关；若固件开发或PWM并发能力不足，放弃直控路线，采用独立主控'
candidate['components'][0]['model']='SU21T'
candidate['components'][1]={'role':'动作控制：拟复用语音模组内部主控，编程能力待验证','model':None}
candidate['tradeoffs']=['有机会减少外部开发板的常开负担与BOM，但必须证明动作编程、三路PWM并发和安全限位均可实现；不能只依据复用引脚表推断']
candidate['risks']=['没有支持三路舵机独立控制的固件证据','只有接口文档，未核对PWM并发、定时器资源和复用限制','全部采购价格、电池和整机功耗仍未知']
candidate['assumptions']=['模块内部主控复用仅为待研究假设，并未验证可实现','第1轮1W监听和2000mAh电池是风险情景，不是SU03T实测；本轮取消该情景输入，未知值恢复为null','SU21T物理第6、7页列出接口及PWM复用，但这不足以审核三路PWM同时可用']
parts=candidate['proposal']['checks'][0]['inputs']['parts']; parts[0]['model']='SU21T'; parts.pop(1)
energy=candidate['proposal']['checks'][1]['inputs']
for field in ('battery_v','capacity_mah','usable_fraction','idle_mw','active_mw'): energy[field]=None
plan['rationale']='上一轮工具计算表明，在1W监听、假设2000mAh电池的情景下能量需求远超可用能量，故研究减少常开组件的路线；阅读SU21T物理6、7页后提出内核复用备选。不能据此判定原路线实际失败或新路线达标，需补编程、PWM、功耗和采购证据。'
plan['response_to']=[failed['observation_id'],'R1:VOICE_LOW']
plan['changes']=[{'candidate_id':'DEV_BOARD','reason':'根据能耗风险情景及已定位的SU21T接口文档，替换为集成动作控制的研究候选；移除外部开发板假设，恢复未知电池和功耗输入，保留100元、48小时及3路PWM约束。','observation_ids':plan['response_to']}]
plan['tasks']=[
 {'id':'VOICE_PWM','question':'SU21T文档明确列出了哪些PWM接口？是否足以证明并发能力？','query':'SU21T PWM','why':'定位引脚页，区分复用功能与同时可用的独立通道数','candidate_ids':['LOW_POWER','DEV_BOARD']},
 {'id':'VOICE_UART','question':'独立主控与集成主控路线的通信接口条件是什么？','query':'SU21T UART','why':'独立MCU路线需要串口协议，直控路线需要固件开发能力；接口存在不等于应用固件已实现','candidate_ids':['LOW_POWER','DEV_BOARD']},
 {'id':'MCU_TIMERS','question':'备用主控有哪些定时器资料可供核验？','query':'STM32L031K6 timer','why':'保留可控的独立主控路线，后续仍需具体引脚映射','candidate_ids':['LOW_POWER']}
]
(root/'examples/robot-design-round2.json').write_text(json.dumps({'plan':plan},ensure_ascii=False,indent=2),encoding='utf-8')
print('已按已读取的真实观察整理第二轮提交；尚未执行或确认选型。')
