"""Offline aggregation of real integration receipts, preserving failed attempts."""
import json
from collections import defaultdict
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED

ROOT=Path(__file__).resolve().parents[1]
base=ROOT/'runtime/expanded-tests'
folders=sorted([p for p in base.iterdir() if p.is_dir()],key=lambda p:p.stat().st_mtime_ns)
calls={};final={};groups=defaultdict(list)
for folder in folders:
    path=folder/'report.json'
    if not path.exists():continue
    report=json.loads(path.read_text(encoding='utf-8'))
    for call in report['calls']:calls[call['call_id']]=call
    for item in report['cases']:
        key={'relation':'evidence_relation','numeric':'evidence_numeric'}.get(item['case'],item['case'])
        final[key]=item['passed'];row_path=folder/(key+'.json')
        if row_path.exists():
            row=json.loads(row_path.read_text(encoding='utf-8'));groups[row.get('category','other')]+=row.get('calls',[])
    for path in folder.glob('*-delivery/report.json'):
        delivery=json.loads(path.read_text(encoding='utf-8'));final[delivery['case']+'_document_delivery']=delivery['passed']
        for call in delivery.get('calls',[]):calls[call['call_id']]=call
        groups['document_delivery']+=delivery.get('calls',[])
rows=list(calls.values());hit=sum(c.get('cache_hit_tokens') or 0 for c in rows);miss=sum(c.get('cache_miss_tokens') or 0 for c in rows)
prompt=sum(c['prompt_tokens'] for c in rows);output=sum(c['completion_tokens'] for c in rows);cost=sum(c['accounted_cny'] for c in rows)
result={'final_cases':final,'calls':len(rows),'cost_cny':cost,'cache_hit_ratio':hit/(hit+miss) if hit+miss else None,
 'prompt_tokens':prompt,'completion_tokens':output,'cache_hit_tokens':hit,'cache_miss_tokens':miss,
 'cold_cache_estimate_cny':prompt*2/1e6+output*8/1e6,'report_folders':[str(f) for f in folders]}
lines=['# 扩展实测与费用缓存报告','','范围为真实模型需求分析、合成取证、真实主机软件编译测试、长上下文与文档交付；不包含MCU固件或硬件验收。首次失败与定向复测均保留，最终状态按最后一次记录统计。','', '| 检查 | 最终结果 |','|---|---|']
for key,passed in final.items():lines.append('| '+key+' | '+('通过' if passed else '未通过')+' |')
lines+=['','## 估算与实测','',f'事前估计20–40次调用，¥1–3。实际{len(rows)}次；输入{prompt:,}、输出{output:,} token。',
 f'按返回usage及官方高峰价保守结算¥{cost:.6f}，包括失败调用；不是平台实时账单。同样输入输出量完全冷缓存估计¥{result["cold_cache_estimate_cny"]:.6f}。',
 f'输入缓存命中{hit:,}、未命中{miss:,} token，加权命中率{result["cache_hit_ratio"]:.2%}。','', '| 类别 | 调用数 | 缓存命中率 | 费用元 |','|---|---:|---:|---:|']
for category,items in groups.items():
    h=sum(c.get('cache_hit_tokens') or 0 for c in items);m=sum(c.get('cache_miss_tokens') or 0 for c in items)
    lines.append(f'| {category} | {len(items)} | {h/(h+m):.2%} | {sum(c["accounted_cny"] for c in items):.6f} |')
lines+=['','相同长文第二次请求约99.6%命中是对照结果，不代表全部任务；首次请求、角色和内容变化会影响命中。软件测试的新短请求未命中，但输入少，费用也很低，不应为了命中率增加无关输入。',
 '', '## 限制与保护','', '本地200KB输入门槛和8192token输出测试额度已移除；真实执行了超过200KB的输入。输出使用官方最大393216token，并按每日剩余人民币预算推导可支付边界。仍受服务端上下文、网络超时、步骤保护和每日¥10保护约束；未知费用请求不自动重放。',
 '请求前预留不是实际扣费；收到可信usage后按输入、缓存与输出结算。',
 '', '## 修复与独立性边界','', '首批10/12通过，计时器动作选择与一次长文JSON结构失败，定向修复与复测后通过。规范化失败现在保留原始响应和参数，反馈列出实际动作与有效动作；初始分析提供明确待办。长文探针明确字段约束。',
 '六种分析由实际AutonomousRunner驱动。取证使用合成资料，不当真实硬件规格。主机原型由模型编写或修复，测试驱动运行真实py_compile和冻结unittest；计数器故障由夹具注入，测试不可由模型修改。文档测试的需求确认和候选选择由测试驱动模拟，不是模型自行审批。',
 '主机测试已扩展到时钟回绕、暂停恢复、按键消抖、串口帧解析、安全锁存、模拟掉电日志恢复、周期调度及串口安全联合控制。后四类新增21个冻结测试，包含2000次固定种子随机状态切换、200组模拟写入中断以及长期调度检查。随机输入可重现，但不是全部输入的穷举。掉电恢复仅模拟内存记录，未验证Flash硬件的原子写入或寿命。源码语法或结构校验失败也进入有限修复循环；离线故障注入确认失败日志反馈和测试哈希保持不变。所有结论只覆盖所列场景，未验证完整联网能力、固件链接、烧录、电气或实物运行。','',
 '官方价格：https://api-docs.deepseek.com/zh-cn/quick_start/pricing/','官方输出上限：https://api-docs.deepseek.com/api/create-chat-completion/']
(base/'扩展测试报告.md').write_text('\n'.join(lines),encoding='utf-8');(base/'汇总.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
with ZipFile(base/'扩展测试记录.zip','w',ZIP_DEFLATED) as z:
    for folder in folders:
        for path in folder.rglob('*'):
            if path.is_file() and path.suffix in ('.json','.md','.html','.csv','.zip'):z.write(path,path.relative_to(base))
    z.write(base/'扩展测试报告.md','扩展测试报告.md')
print(json.dumps(result,ensure_ascii=False))
