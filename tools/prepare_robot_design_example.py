"""Author a case-specific analysis submission. The generic agent never imports this file."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def proposal(voice,mcu,scenario=False):
    parts=[{'model':voice,'quantity':1,'unit_price_cny':None},
           {'model':mcu,'quantity':1,'unit_price_cny':None},
           {'model':'SG90（实际供应商与批次待定）','quantity':3,'unit_price_cny':None},
           {'model':'电池与保护充电方案待定','quantity':1,'unit_price_cny':None},
           {'model':'稳压与舵机断电开关待定','quantity':1,'unit_price_cny':None},
           {'model':'结构、线材与连接件待定','quantity':1,'unit_price_cny':None}]
    return {'checks':[
        {'id':'TOTAL','objective_id':'COST','kind':'budget','inputs':{'limit_cny':100,'shipping_cny':None,'coverage_complete':False,'parts':parts}},
        {'id':'LISTEN48','objective_id':'RUNTIME','kind':'energy','inputs':{'battery_v':3.7 if scenario else None,
          'capacity_mah':2000 if scenario else None,'usable_fraction':0.85 if scenario else None,'reserve_fraction':0.2,
          'hours':48,'idle_mw':1000 if scenario else None,'active_mw':2000 if scenario else None,'active_seconds':150}},
        {'id':'AXES','objective_id':'CONTROL','kind':'resource','inputs':{'resource':'PWM','available':None,'required':3}}
    ]}

def main():
    candidates=[]
    for cid,name,voice,mcu,scenario in [
      ('LOW_POWER','低功耗语音模块＋独立低功耗主控','SU21T','STM32L031K6',False),
      ('DEV_BOARD','常见语音模块＋现成开发板','SU03T','STM32F103C8',True)]:
        candidates.append({'id':cid,'name':name,'architecture':'离线语音模块 → 串口命令 → 主控动作状态机 → 3路舵机；动作结束后切断舵机电源；电池与稳压待定',
          'covers':['REQ-1','REQ-2','REQ-3','REQ-4','REQ-5','REQ-6','REQ-7'],
          'components':[{'role':'语音识别','model':voice},{'role':'动作控制','model':mcu},{'role':'执行机构','model':'SG90 × 3（待供应商核验）'},{'role':'电池、稳压、保护与断电开关','model':None}],
          'tradeoffs':['独立主控便于限制动作和控制断电，但增加成本与待机负担' if not scenario else '现成板便于接线调试，但板上指示灯、稳压器和语音监听可能增加常开功耗'],
          'risks':['没有实际BOM报价，100元约束未证明','整机监听及动作功耗未测量','三个PWM的引脚复用、舵机力矩、堵转电流和机构边界未验证'],
          'assumptions':['三自由度是当前设计分解：摇头、点头、单臂招手；具体机构仍需验证','每48小时累计动作150秒只是演算工况，不是用户确认的验收上限']+
            (['仅用于风险情景：3.7V/2000mAh电池、85%可用率、20%储备、1W监听、2W动作；均不是SU03T、开发板或整机实测参数，也不是最终电池选型'] if scenario else ['所有电源和功耗事实保持未知，不能用芯片休眠电流代替整机监听功耗']),
          'proposal':proposal(voice,mcu,scenario)})
    plan={'analyst':'Codex 外部分析者（本次人工组织分析，无自主模型）',
       'scope':'纸盒机器人：100元总采购、48小时监听、3路PWM的初步比较；不覆盖实机、语音成功率、机构与完整电气验收',
       'rationale':'先比较低功耗专用设计与现成开发板路线；以公开资料检索和保守风险情景检验方向，不给缺少证据的路线自动定案。',
       'objectives':[
         {'id':'COST','description':'全部新购物料、供电、结构和运费不超过100元','kind':'budget','requirement_ids':['REQ-5'],'fixed_inputs':{'limit_cny':100}},
         {'id':'RUNTIME','description':'连续48小时保持语音监听','kind':'energy','requirement_ids':['REQ-4','REQ-7'],'fixed_inputs':{'hours':48}},
         {'id':'CONTROL','description':'本轮三轴机构设计需要3路PWM；不证明引脚复用可同时实现','kind':'resource','requirement_ids':['REQ-1','REQ-2'],'fixed_inputs':{'resource':'PWM','required':3}}],
       'candidates':candidates,'tasks':[
          {'id':'VOICE_LOW','question':'SU21T的低功耗与接口有哪些公开依据？','query':'SU21T','why':'连续监听可能决定48小时续航，先定位原始规格书','candidate_ids':['LOW_POWER']},
          {'id':'VOICE_BOARD','question':'SU03T有哪些规格及硬件设计限制？','query':'SU03T','why':'不根据名称和经验预设整机监听电流','candidate_ids':['DEV_BOARD']},
          {'id':'MCU_LOW','question':'低功耗主控的电源条件和工作模式是什么？','query':'STM32L031K6 current','why':'芯片低功耗能力不能直接替代整机测试','candidate_ids':['LOW_POWER']},
          {'id':'MCU_BOARD','question':'常见主控的电流资料是什么？','query':'STM32F103C8 current','why':'识别开发板路线的供电风险，开发板自身仍需资料与实测','candidate_ids':['DEV_BOARD']} ]}
    path=ROOT/'examples/robot-design-round1.json'; path.write_text(json.dumps({'plan':plan},ensure_ascii=False,indent=2),encoding='utf-8')
    print(path)

if __name__=='__main__': main()
