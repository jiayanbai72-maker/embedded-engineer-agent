"""Export current implementation diagrams as offline SVG/HTML and Mermaid."""
from pathlib import Path
from html import escape
import json
import zipfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs' / 'architecture'
# id, column, row, label, status (implemented / external / integration gap)
DIAGRAMS = [
 ('01-architecture', '总体架构图', '模型负责提出动作；控制器负责约束；工具提供真实执行结果。当前是单模型驱动的本地工程系统。', [
  ('user',1,0,'用户\n需求、确认、模型配置','done'),
  ('web',1,1,'本地工作台\nweb/app.js','done'),
  ('api',1,2,'HTTP API · 8765\nserver.py','done'),
  ('auto',1,3,'自动运行器\nAutonomousRunner','done'),
  ('model',0,3,'决策与上下文整理\nModelDecider / model_context','done'),
  ('budget',0,4,'共享预算与密钥保护\nBudgetModel / DPAPI','done'),
  ('deepseek',0,5,'外部 DeepSeek API\n结构化动作与代码补丁','external'),
  ('ctrl',1,4,'决策控制器\n契约、版本、依赖、权限','done'),
  ('runs',2,4,'运行与回执存储\nruntime/control-runs','done'),
  ('service',1,5,'工程业务服务\nEngineeringService','done'),
  ('evidence',0,6,'资料与参数证据\n文档、原文、页码、未知项','done'),
  ('artifacts',1,6,'方案与工程产物\n接口、连接图、C/H 草案','done'),
  ('tools',2,6,'受控工具适配器\n编译、测试、诊断、回归','done'),
  ('store',1,7,'项目、源码与验证结果\n本地 JSON / 隔离工作目录','done')],
  [('user','web'),('web','api'),('api','auto'),('auto','model'),('model','budget'),('budget','deepseek'),('auto','ctrl'),('ctrl','runs'),('ctrl','service'),('service','evidence'),('service','artifacts'),('service','tools'),('artifacts','store')],
  '箭头表示主要调用方向；模型响应和工具回执沿调用链返回。密钥不进入项目文件或浏览器返回值。'),
 ('02-orchestration', '决策与任务编排图', '每一步依据当前项目与真实回执推进；没有新输入时不会通过反复调用模型解除暂停。', [
  ('start',1,0,'用户启动自动推进','done'),
  ('read',1,1,'读取项目与运行上下文\n需求、计划、近期结果','done'),
  ('gate',1,2,'检查运行前置条件\n确认、状态、重复动作、额度','done'),
  ('pause',0,2,'暂停并说明原因\n等待回答或明确恢复','done'),
  ('decide',1,3,'模型选择下一步\n动作 / 多步计划 / 暂停','external'),
  ('validate',1,4,'契约与执行资格校验\nJSON、版本、ready 任务','done'),
  ('feedback',0,4,'结构化错误反馈\n字段、失败参数、规则','done'),
  ('exec',1,5,'保存待执行动作并执行\npending → executing','done'),
  ('receipt',1,6,'持久化真实回执\n更新任务、项目与修复次数','done'),
  ('next',0,7,'仍有待办或可修复失败\n重新读取上下文','done'),
  ('finish',2,7,'交付已完成\n结束本轮','done')],
  [('start','read'),('read','gate'),('gate','pause'),('gate','decide'),('decide','validate'),('validate','feedback'),('validate','exec'),('exec','receipt'),('receipt','next'),('receipt','finish')],
  '左侧错误反馈和底部待办均可回到“读取上下文”，前提是预算与重试次数允许。用户确认和未知费用暂停不会由模型自行解除。'),
 ('03-build', '工程产物构建与验证图', '把工程草案、对象编译、主机行为测试、完整链接和实物验收分开记录。', [
  ('req',1,0,'需求与验收条件','done'),
  ('design',1,1,'证据、候选方案与功耗\n用户确认条件式方案','done'),
  ('interface',0,2,'接口表\ninterfaces','done'),
  ('circuit',1,2,'连接数据与 SVG 图\ncircuit','done'),
  ('firmware',2,2,'生产源码与原测试\nfirmware','done'),
  ('verify',1,3,'draft_verify\n绑定当前源码哈希','done'),
  ('arm',0,4,'ARMCC Cortex-M0+\n目标文件编译','done'),
  ('host',2,4,'MSVC 主机行为测试\n原测试 + 冻结扩展用例','done'),
  ('result',1,5,'汇总真实验证结果\n失败修复，通过才可交付','done'),
  ('zip',1,6,'交付 ZIP\n源码、图纸、清单、报告','done'),
  ('link',0,7,'当前项目后续：完整链接\n启动文件、驱动、内存布局','gap'),
  ('board',2,7,'当前项目后续：实物验证\n烧录、接线、电气与功能','gap')],
  [('req','design'),('design','interface'),('interface','circuit'),('circuit','firmware'),('firmware','verify'),('verify','arm'),('verify','host'),('arm','result'),('host','result'),('result','zip'),('zip','link'),('link','board')],
  '连接图是工程草案，不是可生产 PCB。当前机器人完成的是对象编译与 mock 测试；完整固件链接、烧录和硬件验收未执行。'),
 ('04-repair', '诊断与定向修复图', '工作台已接入定向修复与冻结扩展测试；独立脚本保留用于诊断演练。', [
  ('failure',1,0,'真实失败与当前源码\n编译日志、断言、文件哈希','done'),
  ('trace',0,1,'隔离诊断重放（可用时）\n实际标量、调用与分支记录','done'),
  ('focus',1,1,'工作台定向修复\nfocused_repair.py','done'),
  ('web',2,1,'工作台自动推进\n失败后切换定向修复','done'),
  ('tests',0,2,'冻结的原测试与额外用例\n补充测试只在隔离目录组合','done'),
  ('model',1,2,'共享预算 → DeepSeek\n模型生成最小补丁','external'),
  ('patch',1,3,'控制器 + draft_patch\n哈希及唯一原文校验','done'),
  ('original',1,4,'原测试与 MCU 编译\n原测试不可删改','done'),
  ('rollback',0,4,'回归保护\n证据可比较时恢复检查点','done'),
  ('extra',1,5,'额外冻结边界测试\n独立报告与用例哈希','done'),
  ('deliver',1,6,'原测试及扩展测试均通过\n服务端才允许交付打包','done')],
  [('failure','trace'),('failure','focus'),('web','focus'),('trace','tests'),('tests','model'),('focus','model'),('model','patch'),('patch','original'),('original','rollback'),('original','extra'),('extra','deliver')],
  '失败回馈下一轮模型修复。诊断重放不是原测试结果；回归恢复不是对任意改动的无条件保证。已关联测试集的源码哈希及测试集哈希均通过后，服务端 execute 才允许交付。'),
 ('05-budget', '费用与上下文控制图', '按人民币预算控制，缓存输入、非缓存输入和输出分别计费，不换算成固定 token 数。', [
  ('state',1,0,'当前必要状态\n保留需求、源码和近期结果','done'),
  ('compact',1,1,'确定性整理上下文\n稳定前缀 + 动态数据','done'),
  ('size',1,2,'检查测试期 200KB 上限\n超限不发出请求','done'),
  ('reserve',1,3,'SQLite 原子预留费用\n每日上限 ¥10','done'),
  ('request',1,4,'DeepSeek API 请求','external'),
  ('usage',0,5,'收到可信 token 用量\n按实际分类结算','done'),
  ('unknown',2,5,'连接失败或费用不确定\n保留预留金额并暂停','done'),
  ('next',0,6,'下一次请求重新检查预算','done'),
  ('confirm',2,6,'用户确认保留预留费用\n恢复后续新请求','done')],
  [('state','compact'),('compact','size'),('size','reserve'),('reserve','request'),('request','usage'),('request','unknown'),('usage','next'),('unknown','confirm')],
  '恢复不重放失败请求、不退还未知费用预留。缓存前缀只提高命中机会；实际命中以 API 用量为准。本地限额不涵盖同一密钥在其他客户端的花费。'),
 ('06-deployment', '本地部署与数据分布图', '当前运行路径是 Windows 本地服务；Docker 和 AgentArts 托管不在本轮工作路径中。', [
  ('browser',0,0,'浏览器工作台\n127.0.0.1:8765','done'),
  ('scripts',2,0,'离线检查与定向修复\ntools/','done'),
  ('server',1,1,'Python 本地 HTTP 服务\n工程服务与控制器','done'),
  ('compile',0,2,'本机 ARMCC / MSVC\n隔离构建目录','done'),
  ('data',1,2,'项目 / 运行 / 报告\nruntime/ 与本地资料库','done'),
  ('ledger',2,2,'共享模型配置与费用账本\nDPAPI + SQLite','done'),
  ('cloud',2,3,'外部 DeepSeek HTTPS API\n启用、授权及预算内调用','external'),
  ('hardware',0,3,'开发板与实物器件\n当前项目未验证','gap')],
  [('browser','server'),('scripts','server'),('server','compile'),('server','data'),('server','ledger'),('ledger','cloud'),('compile','hardware')],
  '文件存储适合当前本地单进程场景，不代表多用户事务或云平台部署。联网搜索和实时报价不能因存在接口模块就视为已接入。')
]

def svg(diagram):
    key,title,subtitle,nodes,edges,note=diagram
    positions={n[0]:(60+n[1]*350,35+n[2]*130) for n in nodes}
    height=max(y for x,y in positions.values())+125
    parts=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1120 {height}" role="img" aria-label="{escape(title)}">',
           '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#738797"/></marker></defs>',
           '<rect width="100%" height="100%" fill="#fff"/>']
    statuses={n[0]:n[4] for n in nodes}
    for a,b in edges:
        x,y=positions[a];u,v=positions[b]
        if y==v:
            if x<u:sx,sy,ex,ey=x+300,y+41,u,v+41
            else:sx,sy,ex,ey=x,y+41,u+300,v+41
            d=f'M{sx},{sy} L{ex},{ey}'
        else:
            sx,sy,ex,ey=x+150,y+82,u+150,v
            middle=(sy+ey)/2
            d=f'M{sx},{sy} C{sx},{middle} {ex},{middle} {ex},{ey}'
        dash=' stroke-dasharray="7 5"' if 'gap' in (statuses[a],statuses[b]) else ''
        parts.append(f'<path d="{d}" fill="none" stroke="#738797" stroke-width="2" marker-end="url(#arrow)"{dash}/>')
    palettes={'done':('#edf6f3','#b8d8cb','#174f40'),'external':('#eef3fc','#bed0ec','#234e87'),'gap':('#fff6e7','#e9c98e','#805a18')}
    for name,col,row,label,state in nodes:
        x,y=positions[name];fill,stroke,color=palettes[state]
        parts.append(f'<rect x="{x}" y="{y}" width="300" height="82" rx="12" fill="{fill}" stroke="{stroke}"/>')
        lines=label.split('\n');start=y+35 if len(lines)>1 else y+48
        for index,line in enumerate(lines):
            size=17 if index==0 else 13
            parts.append(f'<text x="{x+150}" y="{start+index*24}" text-anchor="middle" fill="{color}" font-family="Microsoft YaHei,Arial,sans-serif" font-size="{size}">{escape(line)}</text>')
    parts.append('</svg>')
    content=''.join(parts);ET.fromstring(content)
    return content

def mermaid(diagram):
    _,_,_,nodes,edges,_=diagram
    lines=['flowchart TD']
    statuses={n[0]:n[4] for n in nodes}
    for key,_,_,label,_ in nodes:lines.append('  '+key+'["'+label.replace('\n','<br/>')+'"]')
    for a,b in edges:lines.append('  '+a+(' -.-> ' if 'gap' in (statuses[a],statuses[b]) else ' --> ')+b)
    return '\n'.join(lines)

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    sections=[];md=['# Embedded Engineer Agent：架构、构建与编排\n\n更新：2026-10-18。依据当前源码整理；图中绿色为已实现模块，蓝色为外部模型服务，黄色与虚线为待接入或当前项目未执行部分。\n\n当前不是多模型 Agent 集群。“训练”指诊断反馈、测试用例与修复流程完善，没有训练模型权重。\n']
    for index,d in enumerate(DIAGRAMS,1):
        key,title,subtitle,_,_,note=d
        graphic=svg(d);(OUT/(key+'.svg')).write_text(graphic,encoding='utf-8')
        (OUT/(key+'.mmd')).write_text(mermaid(d),encoding='utf-8')
        sections.append(f'<section id="{key}"><div class="number">图 {index:02}</div><h2>{escape(title)}</h2><p>{escape(subtitle)}</p>{graphic}<aside>{escape(note)}</aside><a download href="{key}.svg">下载 SVG</a></section>')
        md.append(f'## {index}. {title}\n\n{subtitle}\n\n```mermaid\n{mermaid(d)}\n```\n\n{note}\n')
    md.append('''## 模块与实际入口

| 职责 | 实现 |
|---|---|
| 工作台、HTTP、进度 | `src/embedded_agent/server.py`、`src/embedded_agent/web/app.js` |
| 普通自动决策 | `autonomy.py`、`decision_protocol.py`、`model_context.py` |
| 控制、计划、契约和限制 | `control.py`、`planning.py`、`contracts.py`、`runtime_policy.py` |
| 工程业务和工具注册 | `service.py`、`application.py`、`adapters.py` |
| 资料、方案、参数、功耗 | `library.py`、`design.py`、`selection.py`、`power.py` |
| 草案、验证、诊断、回归 | `draft.py`、`draft_verification.py`、`assertion_diagnostics.py`、`repair_coach.py`、`draft_regression.py` |
| 额外测试隔离组合 | `supplemental_tests.py` |
| 本地模型与共享预算 | `local_model.py` |
| 项目存储与交付判定 | `storage.py`、`readiness.py` |
| 独立定向修复 | `tools/run_focused_repair.py` |
| 边界审计与离线回归 | `tools/check_robot_boundaries.py`、`tools/run_offline_curriculum.py` |

表内未写目录的 Python 文件均在 `src/embedded_agent/`。旧 `Workflow / StageAgent` 线性骨架保留，主要用于需求入口；其中阶段占位对象不等于当前工作台所有阶段的执行器。

## 当前验证范围

2026-10-17 的机器人版本已通过原始 mock 测试与新增八类边界用例，并通过 Cortex-M0+ 对象编译；源码、验证结果与交付包按哈希核对。该结果只针对该版本及已有用例，不证明任意工程都能独立完成。完整固件链接、实物验证、电气审查保持未执行。

已验证交付记录：`runtime/focused-repair/20261017-220108/verified-summary.json`。边界审计：`runtime/boundary-audit/20261017-220353/report.json`。不把这些历史记录称为对后续版本的持续有效认证。

## 已有步骤的下一步完善

1. 已接入工作台：失败时定向生成单文件补丁，复测、打包与结束由程序确定性调度。
2. 已接入服务端门禁：已关联冻结测试集的项目必须同时通过原测试与扩展测试，旧报告不能解锁交付。
3. 统一主机编译日志编码，减少中文乱码。
4. 持续补充跨项目边界用例，验证恢复、费用限制与已通过行为。

2026-10-18 更新：上述两项接入已完成，已用离线替身流程和当前项目真实编译复测验证；不据此宣称模型通用独立能力。日志编码与跨项目覆盖继续完善。
''')
    (ROOT/'docs/Agent架构与编排设计.md').write_text('\n'.join(md),encoding='utf-8')
    nav=''.join(f'<a href="#{d[0]}">{i}. {escape(d[1])}</a>' for i,d in enumerate(DIAGRAMS,1))
    html='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Embedded Engineer Agent · 架构设计图</title><style>
*{box-sizing:border-box}body{margin:0;background:#f3f6f8;color:#18313f;font:16px/1.7 "Microsoft YaHei",sans-serif}header,main{max-width:1220px;margin:auto;padding:35px 30px}header{padding-bottom:10px}h1{font-size:32px;line-height:1.4;margin:12px 0}h2{font-size:25px;margin:4px 0}p{color:#576b78;margin:8px 0 20px}.tag,.number{font-size:13px;color:#287460;letter-spacing:1px}nav{display:flex;flex-wrap:wrap;gap:10px;margin:22px 0}a{color:#236d5b;text-decoration:none}nav a{background:white;padding:7px 13px;border:1px solid #d9e3e8;border-radius:7px}section{background:#fff;border:1px solid #dce5e9;border-radius:18px;padding:28px;margin:0 0 28px;scroll-margin-top:20px}svg{display:block;width:100%;height:auto;margin:15px 0}aside{background:#f5f8fa;border-left:3px solid #95b5a9;padding:12px 16px;color:#4a6170;margin-bottom:16px}.legend{display:flex;flex-wrap:wrap;gap:20px}.legend span:before{content:"";display:inline-block;width:12px;height:12px;border-radius:3px;background:#c3dfd1;margin-right:7px}.legend span:nth-child(2):before{background:#bfd1ef}.legend span:nth-child(3):before{background:#efd39b}footer{max-width:1160px;margin:0 auto 35px;color:#687d88}@media print{nav{display:none}body{background:white}section{break-before:page;border:0;padding:0}header{break-after:page}a[download]{display:none}}
</style><header><div class="tag">IMPLEMENTATION MAP · 2026-10-18</div><h1>Embedded Engineer Agent<br>架构、构建与运行编排</h1><p>本地开发阶段 · 按实际源码整理 · 不调用付费模型</p><div class="legend"><span>已实现模块</span><span>外部模型服务</span><span>待接入 / 当前项目未执行</span></div><nav>'''+nav+'</nav></header><main>'+''.join(sections)+'''<section><h2>阅读说明</h2><p>当前是模型决策、程序约束和工具执行组成的本地闭环，不是多模型 Agent 集群。工作台已接入定向修复与已关联冻结测试门禁，独立脚本入口仍保留用于演练。</p><p>原测试与八类额外边界测试通过，仅代表已验证机器人版本的测试覆盖范围。完整固件链接、电气审查、烧录和实物验收未执行。详细模块映射和待办见上级目录 Agent架构与编排设计.md。</p></section></main><footer>离线页面 · SVG 可单独下载，也可使用浏览器打印为 PDF · 图示不是新增能力的完成声明</footer></html>'''
    (OUT/'index.html').write_text(html,encoding='utf-8')
    (OUT/'diagrams.json').write_text(json.dumps(DIAGRAMS,ensure_ascii=False,indent=2),encoding='utf-8')
    with zipfile.ZipFile(ROOT/'docs/Agent架构设计图集.zip','w',zipfile.ZIP_DEFLATED) as z:
        for path in sorted(OUT.iterdir()):
            if path.is_file():z.write(path,'architecture/'+path.name)
        z.write(ROOT/'docs/Agent架构与编排设计.md','Agent架构与编排设计.md')
    print(OUT/'index.html')

if __name__=='__main__':main()
