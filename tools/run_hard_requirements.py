"""Complex live requirement analysis through the real runner in isolated projects."""
import json
from datetime import datetime,timezone
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tools')]
from run_expanded_tests import Metered,analysis_case
from embedded_agent.local_model import LocalSettings

CASES={
 'greenhouse': '设计三分区温室控制器：三个湿度传感器、三个电磁阀、一台共用水泵、水箱低液位检测。只能一个阀开启；阀打开200ms后才能开泵，停机先停泵再延时200ms关阀；传感器超过5秒无新数据立即停该区，缺水或急停立即停泵并锁存，人工复位不能自动重启。单次浇水最多30秒，两次至少间隔60秒。24V外部供电，MCU逻辑3.3V，不能直接驱动负载；断电保存阈值但不得恢复运行态。预算300元只是目标，未报价不能声明满足。只分析需求并给至少两种方案，不采购、不接电、不批准选型。',
 'mobile_robot': '设计蓝牙遥控四轮机器人：左右电机差速、编码器闭环、IMU倾覆检测、前后测距、低电压保护。通信周期20ms，超过200ms无有效新序号指令停车，重放包不能续命；急停和倾覆优先于前进，断线重连不得自动恢复运动，必须显式重新启动。电源2S锂电池，电机堵转电流和容量未知，续航8小时为目标；不得虚构堵转电流、容量或声明已达到续航。无开发板。只做分析、至少两方案和待验证项，不运行实物、不代替用户批准。',
 'conflicting_logger': '设计离线振动记录器，用户同时要求每通道每秒10000样本、8通道、每样本16位、连续保存30天、仅16MB存储且禁止压缩和丢样；1节200mAh电池续航30天，功耗未知，预算100元。不得修改或悄悄放宽用户指标，不得宣称所有指标可同时满足。必须指出存储容量矛盾，给出数据率和30天所需容量估算；续航只能作为未验证目标。给至少两种取舍方案供用户选择，不自行选定或采购。只分析需求。'
}

def main():
 if '--live' not in sys.argv:raise SystemExit('Use --live')
 selected=None
 if '--only' in sys.argv:
  selected=set(sys.argv[sys.argv.index('--only')+1].split(','))
  if not selected.issubset(CASES):raise SystemExit('Unknown case')
 model=Metered(LocalSettings(ROOT).model());folder=ROOT/'runtime/hard-requirements'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ');folder.mkdir(parents=True);rows=[]
 for name,description in CASES.items():
  if selected is not None and name not in selected:continue
  start=len(model.calls)
  try:row=analysis_case(model,name,description)
  except Exception as exc:row={'case':name,'passed':False,'error':str(exc)}
  row['calls']=model.calls[start:];row['semantic_review']='pending human evidence review; structural pass alone is insufficient'
  (folder/(name+'.json')).write_text(json.dumps(row,ensure_ascii=False,indent=2),encoding='utf-8')
  rows.append({'case':name,'structural_pass':row['passed'],'calls':len(row['calls'])});print(rows[-1],flush=True)
  if model.budget.status()['paused']:break
 hit=sum(c.get('cache_hit_tokens') or 0 for c in model.calls);miss=sum(c.get('cache_miss_tokens') or 0 for c in model.calls)
 report={'cases':rows,'calls':model.calls,'cost_cny':sum(c['accounted_cny'] for c in model.calls),'cache_hit_tokens':hit,'cache_miss_tokens':miss,'cache_hit_ratio':hit/(hit+miss) if hit+miss else None,'scope':'requirement analysis only; no implementation or hardware validation'}
 (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(folder,flush=True)

if __name__=='__main__':main()
